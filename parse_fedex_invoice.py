import json
import re
import sys
from decimal import Decimal
from pathlib import Path


HEADER_RE = re.compile(
    r'^(?P<shipment>\d+)\s+(?P<ship_date>\d{2}/\d{2}/\d{4})\s+'
    r'(?P<service>.+?)\s+(?P<pieces>\d+)\s+(?P<weight>\d+(?:\.\d+)?\s*kg)\s+'
    r'(?P<reference>\S+)\s+(?P<freight>[\d,]+\.\d+)\s+(?P<other_charges>[\d,]+\.\d+)\s+(?P<total>[\d,]+\.\d+)',
    re.M,
)

DIMS_RE = re.compile(r'Dims:\s*(?P<dims>.+?)\s+Billed Weight:\s*(?P<billed_weight>[\d\.]+\s*kg)')

# More resilient: capture amounts that appear to the right or on the next line of each label
NUM_PATTERN = r'-?[\d,]+(?:\.\d+)?'
TRANSPORT_AFTER_RE = re.compile(r'Transportation\s+Charge[^\d\n]*(' + NUM_PATTERN + ')', re.I)
DISCOUNT_AFTER_RE = re.compile(r'Discount[^\d\n]*(' + NUM_PATTERN + ')', re.I)
FUEL_AFTER_RE = re.compile(r'Fuel\s+Surcharge[^\d\n]*(' + NUM_PATTERN + ')', re.I)

# Amount BEFORE the label on the same line (e.g., "17,853.00 ... Transportation Charge")
TRANSPORT_BEFORE_RE = re.compile(r'(' + NUM_PATTERN + r')[^\n]*Transportation\s+Charge', re.I)
DISCOUNT_BEFORE_RE = re.compile(r'(' + NUM_PATTERN + r')[^\n]*Discount', re.I)
FUEL_BEFORE_RE = re.compile(r'(' + NUM_PATTERN + r')[^\n]*Fuel\s+Surcharge', re.I)

TENDER_SUBTOTAL_RE = re.compile(
    r'Tendered Date:\s*(?P<tendered_date>\d{2}/\d{2}/\d{4}).*?Subtotal INR\s*(?P<subtotal>[\d,]+\.\d+)',
    re.S,
)


NUM_RE = re.compile(r'-?[\d,]+\.\d+')


def _find_amount_after_label(block_text: str, label: str) -> str | None:
    """Find the first currency-looking number on the same or next few lines after a label.

    This handles layouts where the amount is printed under an 'Amount' column on the next line.
    """
    lines = block_text.splitlines()
    label_lower = label.lower()
    for idx, line in enumerate(lines):
        if label_lower in line.lower():
            # Search on the same line first
            m = NUM_RE.search(line)
            if m:
                return m.group(0)
            # Then search a few lines below (up to 3 lines)
            for j in range(1, 4):
                k = idx + j
                if k >= len(lines):
                    break
                m2 = NUM_RE.search(lines[k])
                if m2:
                    return m2.group(0)
            break
    return None


def _find_amount_near_label(block_text: str, label: str, window: int = 3) -> str | None:
    """Find the first currency-looking number within ±window lines of the label.

    Looks on the same line, then next lines, then previous lines.
    """
    lines = block_text.splitlines()
    label_lower = label.lower()
    for idx, line in enumerate(lines):
        if label_lower in line.lower():
            candidates: list[str] = []
            # same line - collect all numbers
            for m in NUM_RE.finditer(line):
                tail = line[m.end(): m.end() + 3]
                head = line[max(0, m.start() - 3): m.start()]
                if '%' in tail or '%' in head:
                    continue
                if 'kg' in tail.lower() or 'kg' in head.lower():
                    continue
                candidates.append(m.group(0))
            # next lines
            for j in range(1, window + 1):
                k = idx + j
                if k < len(lines):
                    L = lines[k]
                    for m in NUM_RE.finditer(L):
                        tail = L[m.end(): m.end() + 3]
                        head = L[max(0, m.start() - 3): m.start()]
                        if '%' in tail or '%' in head:
                            continue
                        if 'kg' in tail.lower() or 'kg' in head.lower():
                            continue
                        candidates.append(m.group(0))
            # previous lines
            for j in range(1, window + 1):
                k = idx - j
                if k >= 0:
                    L = lines[k]
                    for m in NUM_RE.finditer(L):
                        tail = L[m.end(): m.end() + 3]
                        head = L[max(0, m.start() - 3): m.start()]
                        if '%' in tail or '%' in head:
                            continue
                        if 'kg' in tail.lower() or 'kg' in head.lower():
                            continue
                        candidates.append(m.group(0))

            if not candidates:
                return None
            # choose candidate with largest absolute value
            def to_decimal(s: str) -> Decimal:
                return Decimal(s.replace(',', ''))

            best = max(candidates, key=lambda s: abs(to_decimal(s)))
            return best
    return None


def _line_starts_with_number(line: str) -> str | None:
    m = re.match(r"\s*(" + NUM_RE.pattern + ")", line)
    if not m:
        return None
    token = m.group(1)
    # Reject percentages and weights
    tail = line[m.end(): m.end() + 3]
    if '%' in tail:
        return None
    return token


def _find_amount_for_label(block_text: str, label: str, window: int = 3) -> str | None:
    """Pick the amount on the same line immediately before the label; otherwise
    use the nearest previous/next line that starts with a currency number.
    This mirrors the visual table layout in the FedEx invoice detail.
    """
    lines = block_text.splitlines()
    label_lower = label.lower()
    for idx, line in enumerate(lines):
        low = line.lower()
        if label_lower in low:
            label_pos = low.find(label_lower)
            # Same line: choose the last number BEFORE the label
            candidates_same_line: list[tuple[int, str]] = []
            for m in NUM_RE.finditer(line):
                if m.start() < label_pos:
                    head = line[max(0, m.start() - 3): m.start()]
                    tail = line[m.end(): m.end() + 3]
                    if '%' in head or '%' in tail:
                        continue
                    if 'kg' in head.lower() or 'kg' in tail.lower():
                        continue
                    candidates_same_line.append((m.start(), m.group(0)))
            if candidates_same_line:
                # nearest to the label (max start index)
                return sorted(candidates_same_line, key=lambda p: p[0])[-1][1]

            # Previous lines: find the closest line above that starts with number
            for j in range(1, window + 1):
                k = idx - j
                if k >= 0:
                    tok = _line_starts_with_number(lines[k])
                    if tok:
                        return tok
            # Next lines: as fallback
            for j in range(1, window + 1):
                k = idx + j
                if k < len(lines):
                    tok = _line_starts_with_number(lines[k])
                    if tok:
                        return tok
            break
    return None

def _slice_charges_section(block_text: str) -> str:
    """Return the substring that contains the Charges table to reduce false matches.

    Heuristics:
    - Start at the first occurrence of the word "Charges" (often appears as "Charges" or "Charges  Amount").
    - End at the first of ["Signed", "Tendered Date", "Subtotal INR"].
    If not found, return the whole block.
    """
    lower = block_text.lower()
    start_idx = lower.find('charges')
    if start_idx == -1:
        return block_text
    end_candidates = []
    for token in ['signed', 'tendered date', 'subtotal inr']:
        pos = lower.find(token, start_idx + 7)
        if pos != -1:
            end_candidates.append(pos)
    end_idx = min(end_candidates) if end_candidates else None
    if end_idx is not None and end_idx > start_idx:
        return block_text[start_idx:end_idx]
    return block_text[start_idx:]


def _numbers_in_segment(seg: str) -> list[str]:
    candidates: list[str] = []
    for m in NUM_RE.finditer(seg):
        head = seg[max(0, m.start() - 3): m.start()]
        tail = seg[m.end(): m.end() + 3]
        if '%' in head or '%' in tail:
            continue
        if 'kg' in head.lower() or 'kg' in tail.lower():
            continue
        candidates.append(m.group(0))
    return candidates


def _amount_from_label_line(charges_text: str, label: str) -> str | None:
    label_lower = label.lower()
    for line in charges_text.splitlines():
        low = line.lower()
        if label_lower in low:
            pos = low.find(label_lower)
            before = line[:pos]
            after = line[pos + len(label):]
            nums_before = _numbers_in_segment(before)
            if nums_before:
                return nums_before[-1]
            nums_after = _numbers_in_segment(after)
            if nums_after:
                return nums_after[0]
            return None
    return None


def parse_blocks(pdf_text: str):
    matches = list(HEADER_RE.finditer(pdf_text))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(pdf_text)
        block_text = pdf_text[start:end]
        data = {
            'shipment': m.group('shipment'),
            'ship_date': m.group('ship_date'),
            'service': m.group('service').strip(),
            'pieces': m.group('pieces'),
            'weight': m.group('weight').strip(),
            'reference': m.group('reference'),
            'freight': m.group('freight'),
            'other_charges': m.group('other_charges'),
            'total': m.group('total'),
        }
        dims = DIMS_RE.search(block_text)
        if dims:
            data['dims'] = dims.group('dims').strip()
            data['billed_weight'] = dims.group('billed_weight').strip()
        # Charges: search within the Charges section only
        charges_text = _slice_charges_section(block_text)
        charges = {}
        # Prefer the number on the same line as each label; then fall back to patterns
        tr_val = _amount_from_label_line(charges_text, 'Transportation Charge')
        ds_val = _amount_from_label_line(charges_text, 'Discount')
        fu_val = _amount_from_label_line(charges_text, 'Fuel Surcharge')

        if not tr_val:
            m_tr = TRANSPORT_AFTER_RE.search(charges_text) or TRANSPORT_BEFORE_RE.search(charges_text)
            tr_val = m_tr.group(1) if m_tr else _find_amount_for_label(charges_text, 'Transportation Charge')
        if not ds_val:
            m_ds = DISCOUNT_AFTER_RE.search(charges_text) or DISCOUNT_BEFORE_RE.search(charges_text)
            ds_val = m_ds.group(1) if m_ds else _find_amount_for_label(charges_text, 'Discount')
        if not fu_val:
            m_fu = FUEL_AFTER_RE.search(charges_text) or FUEL_BEFORE_RE.search(charges_text)
            fu_val = m_fu.group(1) if m_fu else _find_amount_for_label(charges_text, 'Fuel Surcharge')

        if tr_val:
            charges['transportation_charge'] = tr_val
        if ds_val:
            charges['discount'] = ds_val
        if fu_val:
            charges['fuel_surcharge'] = fu_val
        if charges:
            data['charges'] = charges
            # Also expose at top-level for convenience
            if 'transportation_charge' in charges:
                data['transportation_charge'] = charges['transportation_charge']
            if 'discount' in charges:
                data['discount'] = charges['discount']
            if 'fuel_surcharge' in charges:
                data['fuel_surcharge'] = charges['fuel_surcharge']

        # Enforce: fuel_surcharge must equal other_charges
        if data.get('other_charges'):
            data['fuel_surcharge'] = data['other_charges']
            if 'charges' in data:
                data['charges']['fuel_surcharge'] = data['other_charges']
        tender = TENDER_SUBTOTAL_RE.search(block_text)
        if tender:
            data['tendered_date'] = tender.group('tendered_date')
            data['subtotal_inr'] = tender.group('subtotal')
        yield data


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python parse_fedex_invoice.py <fedex.txt> [--list] [--ref REFERENCE]')
        return 2
    txt_path = Path(sys.argv[1])
    if not txt_path.exists():
        print(f'Missing text file: {txt_path}. Run extract_pdf_text.py first.')
        return 1

    text = txt_path.read_text(encoding='utf-8', errors='ignore')
    blocks = list(parse_blocks(text))

    # options
    if '--list' in sys.argv:
        refs = sorted({b.get('reference') for b in blocks if b.get('reference')})
        print('\n'.join(refs))
        return 0

    if '--ref' in sys.argv:
        try:
            idx = sys.argv.index('--ref')
            ref = sys.argv[idx + 1]
        except Exception:
            print('Provide a reference string after --ref')
            return 2
        selection = [b for b in blocks if b.get('reference') == ref]
        print(json.dumps(selection[0] if len(selection) == 1 else selection, ensure_ascii=False, indent=2))
        return 0

    # default: dump all blocks as JSON
    print(json.dumps(blocks, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


