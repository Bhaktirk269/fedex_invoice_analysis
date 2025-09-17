from fastapi import FastAPI, Query, UploadFile, File
from pathlib import Path
import json
import fitz  # PyMuPDF
import easyocr
import tempfile

# Local parsers
from parse_fedex_invoice import parse_blocks as fedex_parse_blocks
from parse_ups_invoice import (
    parse_ups as ups_parse,
    parse_summary as ups_parse_summary,
    parse_shipment_by_tracking as ups_by_tracking_parser,
    parse_shipment_by_reference as ups_by_reference_parser,
)


app = FastAPI(title="Invoice Parser API")


_easyocr_reader = None


def get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        _easyocr_reader = easyocr.Reader(['en'], gpu=False)
    return _easyocr_reader


def ocr_pdf_to_text(pdf_path: Path, dpi: int = 200) -> str:
    doc = fitz.open(str(pdf_path))
    reader = get_easyocr_reader()
    all_text: list[str] = []
    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")
        result = reader.readtext(img_bytes, detail=0, paragraph=True)
        all_text.append("\n".join(result))
    return "\n\n".join(all_text)


@app.get("/fedex/refs")
def list_fedex_references(file: str = Query("fedex.txt")):
    p = Path(file)
    text = p.read_text(encoding="utf-8", errors="ignore")
    blocks = list(fedex_parse_blocks(text))
    refs = sorted({b.get('reference') for b in blocks if b.get('reference')})
    return {"references": refs}


@app.get("/fedex/by-ref/{reference}")
def fedex_by_reference(reference: str, file: str = Query("fedex.txt")):
    p = Path(file)
    text = p.read_text(encoding="utf-8", errors="ignore")
    blocks = list(fedex_parse_blocks(text))
    match = [b for b in blocks if b.get('reference') == reference]
    if not match:
        return {"error": "reference not found", "reference": reference}
    return match[0] if len(match) == 1 else match


@app.get("/ups/summary")
def ups_summary(file: str = Query("ups.txt")):
    p = Path(file)
    text = p.read_text(encoding="utf-8", errors="ignore")
    return ups_parse_summary(text)


@app.get("/ups/records")
def ups_list_records(file: str = Query("ups.txt")):
    p = Path(file)
    text = p.read_text(encoding="utf-8", errors="ignore")
    records = ups_parse(text)
    recs = sorted({r.get('record_number') for r in records if r.get('record_number')})
    return {"records": recs}


@app.get("/ups/by-record/{record_number}")
def ups_by_record(record_number: str, file: str = Query("ups.txt")):
    p = Path(file)
    text = p.read_text(encoding="utf-8", errors="ignore")
    records = ups_parse(text)
    sel = [r for r in records if r.get('record_number') == record_number]
    if not sel:
        return {"error": "record not found", "record_number": record_number}
    return sel[0] if len(sel) == 1 else sel


@app.get("/ups/by-invoice/{original_invoice}")
def ups_by_invoice(original_invoice: str, file: str = Query("ups.txt")):
    p = Path(file)
    text = p.read_text(encoding="utf-8", errors="ignore")
    records = ups_parse(text)
    sel = [r for r in records if r.get('original_invoice') == original_invoice]
    # compute totals
    def to_dec(s: str) -> float:
        return float(s.replace(',', ''))
    total_adjustments = sum(to_dec(r['net_charges']) for r in sel if r.get('net_charges'))
    summary = ups_parse_summary(text)
    total_adjustments_str = summary.get('adjustments') if summary.get('adjustments') else f"{total_adjustments:,.2f}"
    total_debit_for_record = [
        {"record_number": r.get('record_number'), "rs": (r.get('total_debit_amount') or r.get('net_charges'))}
        for r in sel if r.get('record_number') and (r.get('total_debit_amount') or r.get('net_charges'))
    ]
    trimmed_summary = dict(summary)
    trimmed_summary.pop('place_of_supply', None)
    return {
        "original_invoice": original_invoice,
        "total_adjustments_charges": total_adjustments_str,
        "total_amount": summary.get('total_amount'),
        "Total Debit for Record No.": total_debit_for_record,
        "summary": trimmed_summary,
    }


@app.get("/ups/by-tracking/{tracking}")
def ups_by_tracking(tracking: str, file: str = Query("ups.txt")):
    p = Path(file)
    text = p.read_text(encoding="utf-8", errors="ignore")
    return ups_by_tracking_parser(text, tracking)


@app.get("/ups/by-reference")
def ups_by_reference(ref2: str, ref1: str | None = Query(None), file: str = Query("ups.txt")):
    p = Path(file)
    text = p.read_text(encoding="utf-8", errors="ignore")
    return ups_by_reference_parser(text, ref2=ref2, ref1=ref1)



@app.post("/ups/upload")
async def ups_upload(file: UploadFile = File(...), dpi: int = Query(200)):
    """Upload a UPS invoice PDF and return all parsed shipment details as JSON.

    This keeps existing endpoints unchanged and adds a convenient upload flow.
    """
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            contents = await file.read()
            tmp.write(contents)
            tmp_path = Path(tmp.name)
        text = ocr_pdf_to_text(tmp_path, dpi=dpi)
        records = ups_parse(text)
        summary = ups_parse_summary(text)
        return {"summary": summary, "records": records}
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

@app.get("/ups/by-reference-ocr")
def ups_by_reference_ocr(ref2: str, ref1: str | None = Query(None), pdf_file: str = Query("ups_invoice.pdf")):
    p = Path(pdf_file)
    if not p.exists():
        return {"error": "pdf not found", "pdf_file": pdf_file}
    text = ocr_pdf_to_text(p)
    return ups_by_reference_parser(text, ref2=ref2, ref1=ref1)


