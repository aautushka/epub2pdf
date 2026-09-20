#!/usr/bin/env python3
"""
epub2pdf — Convert EPUB to a beautifully formatted PDF for iPad Pro.
Usage: python epub2pdf.py input.epub [output.pdf]
"""

import argparse
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET


# ── iPad Pro 12.9" portrait dimensions ──────────────────────────────────────
PAGE_WIDTH  = "7.76in"
PAGE_HEIGHT = "10.34in"

PAGE_CSS = r"""
/* Reset */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

/* Page */
@page {
  size: 7.76in 10.34in;
  margin: 0.72in 0.70in;
}

/* Base */
html { font-size: 11pt; }
body {
  font-family: Georgia, "Palatino Linotype", "Book Antiqua", serif;
  line-height: 1.62;
  color: #181818;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  orphans: 3;
  widows: 3;
}

/* Chapter breaks */
div.chapter { page-break-before: always; }
div.chapter:first-of-type { page-break-before: avoid; }

/* Headings */
h1, h2, h3, h4, h5, h6 {
  font-family: Georgia, serif;
  color: #111;
  line-height: 1.25;
  margin: 1.4em 0 0.45em;
  page-break-after: avoid;
}
h1 {
  font-size: 1.85em;
  padding-bottom: 0.18em;
  border-bottom: 1.5px solid #ccc;
  page-break-before: always;
}
div.chapter:first-of-type h1:first-child { page-break-before: avoid; }
h2 { font-size: 1.35em; }
h3 { font-size: 1.12em; }
h4 { font-size: 1em; font-style: italic; }
h5, h6 { font-size: 0.95em; font-weight: bold; }

/* Paragraphs */
p { margin-bottom: 0.55em; text-align: justify; hyphens: auto; }
p + p { text-indent: 1.5em; margin-top: 0; margin-bottom: 0; }
h1 + p, h2 + p, h3 + p, h4 + p,
blockquote + p, figure + p { text-indent: 0; }

/* Links */
a { color: #1e4d9e; text-decoration: none; }

/* Images */
img {
  max-width: 100%;
  max-height: 9in;
  height: auto;
  display: block;
  margin: 1em auto;
  page-break-inside: avoid;
}
figure { page-break-inside: avoid; margin: 1.2em 0; text-align: center; }
figcaption { font-size: 0.84em; color: #555; font-style: italic; margin-top: 0.3em; }

/* Blockquote */
blockquote {
  margin: 1em 1.6em;
  padding: 0.4em 1em;
  border-left: 3px solid #bbb;
  color: #444;
  font-style: italic;
}

/* Code */
code, kbd, samp {
  font-family: "Menlo", "Courier New", monospace;
  font-size: 0.87em;
  background: #f4f4f4;
  padding: 0.05em 0.25em;
  border-radius: 2px;
}
pre {
  font-family: "Menlo", "Courier New", monospace;
  font-size: 0.84em;
  background: #f5f5f5;
  border: 1px solid #ddd;
  padding: 0.8em 1em;
  border-radius: 3px;
  page-break-inside: avoid;
  margin: 1em 0;
  white-space: pre-wrap;
  word-break: break-all;
}
pre code { background: none; padding: 0; font-size: inherit; }

/* Tables */
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9em;
  margin: 1em 0;
  page-break-inside: avoid;
}
th, td { border: 1px solid #c8c8c8; padding: 0.35em 0.65em; text-align: left; }
th { background: #efefef; font-weight: 700; }
tr:nth-child(even) td { background: #f9f9f9; }

/* Lists */
ul, ol { margin: 0.5em 0 0.6em 1.9em; }
li { margin-bottom: 0.2em; }
li p { text-indent: 0; }

/* Horizontal rule */
hr { border: none; border-top: 1px solid #ccc; margin: 1.4em 0; }

/* Footnotes */
.footnote, .footnotes { font-size: 0.85em; color: #555; border-top: 1px solid #ddd; margin-top: 1.5em; padding-top: 0.5em; }
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def check_deps() -> None:
    missing = []
    try:
        import bs4  # noqa: F401
    except ImportError:
        missing.append("beautifulsoup4")
    try:
        import playwright  # noqa: F401
    except ImportError:
        missing.append("playwright")
    if missing:
        die(
            f"Missing packages: pip install {' '.join(missing)}\n"
            "Also run: playwright install chromium"
        )


def extract_epub(epub_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(epub_path) as zf:
        zf.extractall(dest)


def find_opf(root: Path) -> Path:
    container = ET.parse(root / "META-INF" / "container.xml")
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    opf_rel = container.find(".//c:rootfile", ns).get("full-path")
    return root / opf_rel


def parse_opf(opf_path: Path) -> tuple[dict, list[Path]]:
    opf_dir = opf_path.parent
    tree = ET.parse(opf_path)
    ns = {
        "opf": "http://www.idpf.org/2007/opf",
        "dc":  "http://purl.org/dc/elements/1.1/",
    }

    meta: dict[str, str] = {}
    for tag in ("title", "creator", "language"):
        el = tree.find(f".//dc:{tag}", ns)
        if el is not None and el.text:
            meta[tag] = el.text.strip()

    # Manifest: id → path (HTML/XHTML only)
    manifest: dict[str, Path] = {}
    for item in tree.findall(".//opf:item", ns):
        iid = item.get("id", "")
        href = item.get("href", "")
        mt   = item.get("media-type", "")
        if href and ("html" in mt or "xhtml" in mt):
            manifest[iid] = opf_dir / unquote(href)

    # Spine order
    spine: list[Path] = []
    for itemref in tree.findall(".//opf:itemref", ns):
        idref = itemref.get("idref", "")
        if idref in manifest:
            p = manifest[idref]
            if p.exists():
                spine.append(p)

    return meta, spine


def chapter_body(html_path: Path) -> str:
    """Return the inner body content of a chapter with absolute image paths."""
    from bs4 import BeautifulSoup

    raw = html_path.read_bytes()
    # lxml-xml preserves namespaces; html.parser is fine for HTML5
    parser = "lxml-xml" if html_path.suffix.lower() in (".xhtml", ".xml") else "lxml"
    try:
        soup = BeautifulSoup(raw, parser)
    except Exception:
        soup = BeautifulSoup(raw, "html.parser")

    # Resolve image paths to absolute file:// URIs
    for tag in soup.find_all(True):
        for attr in ("src", "href", "xlink:href"):
            val = tag.get(attr, "")
            if val and not val.startswith(("http://", "https://", "data:", "file://")):
                resolved = (html_path.parent / unquote(val)).resolve()
                if resolved.exists():
                    tag[attr] = resolved.as_uri()

    body = soup.find("body")
    if body:
        return f'<div class="chapter">\n{body.decode_contents()}\n</div>'
    return f'<div class="chapter">\n{str(soup)}\n</div>'


def render_pdf(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.as_uri(), wait_until="networkidle")
        page.pdf(
            path=str(pdf_path),
            width=PAGE_WIDTH,
            height=PAGE_HEIGHT,
            print_background=True,
            display_header_footer=False,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        )
        browser.close()


def main() -> None:
    check_deps()

    ap = argparse.ArgumentParser(description="Convert EPUB to PDF for iPad Pro.")
    ap.add_argument("epub",   type=Path, help="Input .epub file")
    ap.add_argument("output", type=Path, nargs="?", help="Output .pdf (default: same stem as input)")
    args = ap.parse_args()

    epub_path: Path = args.epub.resolve()
    if not epub_path.exists():
        die(f"File not found: {epub_path}")
    if epub_path.suffix.lower() != ".epub":
        die(f"Expected an .epub file, got: {epub_path.name}")

    pdf_path: Path = (args.output or epub_path.with_suffix(".pdf")).resolve()

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)

        print(f"Extracting  {epub_path.name} …")
        extract_epub(epub_path, tmp)

        print("Parsing OPF …")
        opf_path = find_opf(tmp)
        meta, spine = parse_opf(opf_path)

        if not spine:
            die("No readable chapters found in EPUB spine.")

        print(f"  Title   : {meta.get('title', '(unknown)')}")
        if meta.get("creator"):
            print(f"  Author  : {meta['creator']}")
        print(f"  Chapters: {len(spine)}")

        print("Building merged HTML …")
        chapters = [chapter_body(p) for p in spine]
        html = HTML_TEMPLATE.format(
            lang=meta.get("language", "en"),
            title=meta.get("title", epub_path.stem),
            css=PAGE_CSS,
            body="\n".join(chapters),
        )

        html_file = tmp / "_merged.html"
        html_file.write_text(html, encoding="utf-8")

        print("Rendering PDF via Chromium …")
        render_pdf(html_file, pdf_path)

    print(f"\nDone → {pdf_path}")


if __name__ == "__main__":
    main()
