import sys
from pathlib import Path
from pdfminer.high_level import extract_text


def extract_pdf_to_txt(pdf_path: Path, output_path: Path) -> None:
    text = extract_text(str(pdf_path))
    output_path.write_text(text, encoding="utf-8")


def main() -> int:
    # If specific files are provided, use them; otherwise, process all PDFs in cwd
    args = sys.argv[1:]
    pdf_files = []
    if args:
        pdf_files = [Path(a) for a in args]
    else:
        pdf_files = sorted(Path.cwd().glob("*.pdf"))

    if not pdf_files:
        print("No PDF files found.")
        return 1

    for pdf in pdf_files:
        if not pdf.exists() or pdf.suffix.lower() != ".pdf":
            print(f"Skipping non-existent or non-PDF: {pdf}")
            continue
        output_txt = pdf.with_suffix(".txt")
        try:
            print(f"Extracting: {pdf} -> {output_txt}")
            extract_pdf_to_txt(pdf, output_txt)
        except Exception as exc:
            print(f"Failed to extract {pdf}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


