import sys
from pathlib import Path
import argparse
import fitz  # PyMuPDF
import easyocr


def ocr_pdf_to_txt(pdf_path: Path, output_path: Path, dpi: int = 300, lang: str = 'en', gpu: bool = False) -> None:
    doc = fitz.open(str(pdf_path))
    reader = easyocr.Reader([lang], gpu=gpu)
    all_text = []
    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        # Use grayscale to improve OCR and reduce size
        pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csGRAY)
        img_bytes = pix.tobytes("png")
        result = reader.readtext(img_bytes, detail=0, paragraph=True)
        all_text.append("\n".join(result))
    output_path.write_text("\n\n".join(all_text), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR PDF(s) to text using EasyOCR + PyMuPDF")
    parser.add_argument("files", nargs='+', help="PDF files to OCR")
    parser.add_argument("--dpi", type=int, default=300, help="Rendering DPI (higher = better, slower)")
    parser.add_argument("--lang", type=str, default="en", help="OCR language code (default: en)")
    parser.add_argument("--gpu", action="store_true", help="Use GPU if available")
    args = parser.parse_args()

    for arg in args.files:
        pdf = Path(arg)
        if not pdf.exists() or pdf.suffix.lower() != ".pdf":
            print(f"Skipping non-existent or non-PDF: {pdf}")
            continue
        out = pdf.with_suffix(".ocr.txt")
        print(f"OCR: {pdf} -> {out} (dpi={args.dpi}, lang={args.lang}, gpu={args.gpu})")
        try:
            ocr_pdf_to_txt(pdf, out, dpi=args.dpi, lang=args.lang, gpu=args.gpu)
        except Exception as exc:
            print(f"Failed OCR {pdf}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


