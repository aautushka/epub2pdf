# epub2pdf

Converts EPUB files to typographically formatted PDFs for tablet reading.

## Requirements

```
pip install -r requirements.txt
playwright install chromium
```

Tesseract must be installed separately (used for OCR-based image sizing):

```
brew install tesseract        # macOS
apt install tesseract-ocr     # Debian/Ubuntu
```

## Usage

```
python epub2pdf.py input.epub [output.pdf] [--device DEVICE] [--no-cv] [--no-sr]
```

| Option | Description |
|---|---|
| `--device ipad-pro` | iPad Pro 12.9" — 7.76 × 10.34 in (default) |
| `--device ipad` | iPad 9th gen / Huawei MatePad 10.3" — 6.14 × 8.18 in |
| `--no-cv` | Disable OCR-based image sizing |
| `--no-sr` | Disable super-resolution upscaling of formula images |

If no output path is given, the PDF is written next to the input file with the same stem.

## What it does

- Extracts EPUB chapters in spine order and merges them into a single HTML document
- Applies print CSS: Iowan Old Style serif, justified text, drop caps, running header, page numbers
- Renders to PDF via headless Chromium (Playwright)
- Cover pages and other image-only spine items are rendered full-bleed (no margins, no header/footer)
- OCR estimates printed size of inline images to reproduce their intended dimensions
- Small formula images are super-resolved 4× before embedding

## Running tests

```
python -m pytest tests/
```
