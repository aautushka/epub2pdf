#!/usr/bin/env python3
"""
epub2pdf — Convert EPUB to a beautifully formatted PDF for iPad Pro.
Usage: python epub2pdf.py input.epub [output.pdf] [--no-cv] [--no-sr]
"""

import argparse
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET


# ── iPad Pro 12.9" portrait dimensions ──────────────────────────────────────
PAGE_WIDTH       = "7.76in"
PAGE_HEIGHT      = "10.34in"
CONTENT_WIDTH_IN  = 7.76 - 2 * 1.15   # usable width after margins = 5.46in
TARGET_LABEL_PT   = 8.0               # chart/diagram labels should render at ~8pt
SR_MAX_HEIGHT_PX  = 250               # images shorter than this are formula candidates
SR_MAX_SAT_STD    = 0.05              # saturation std below this → near-grayscale
SR_SCALE          = 4                 # upscale factor for formula images
FORMULA_DPI       = 200               # assumed DPI for sizing formula images by original height

PAGE_CSS = r"""
/* Reset */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

/* Page — margins controlled by Playwright, not here */
@page { size: 7.76in 10.34in; }

/* Base */
html { font-size: 12pt; }
body {
  font-family: "Baskerville", "Hoefler Text", "Palatino Linotype", "Book Antiqua", Georgia, serif;
  line-height: 1.46;
  color: #181818;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  overflow-wrap: break-word; /* prevent long URLs in notes from triggering Chromium page scaling */
  orphans: 3;
  widows: 3;
}

/* Headings */
h1, h2, h3, h4, h5, h6 {
  color: #111;
  page-break-after: avoid;
  page-break-inside: avoid;
}
h1 {
  font-size: 1.6em;
  font-weight: normal;
  text-align: center;
  letter-spacing: 0.04em;
  line-height: 1.2;
  margin: 1.6em 0 1.0em;
  padding-bottom: 0.5em;
  border-bottom: 0.75pt solid #bbb;
}
/* chapter-number h1 followed by chapter-title h1: suppress double border */
h1:has(+ h1) { border-bottom: none; padding-bottom: 0; margin-bottom: 0.15em; }
h2 {
  font-size: 1em;
  font-weight: normal;
  font-variant: small-caps;
  font-variant-caps: small-caps;
  letter-spacing: 0.08em;
  line-height: 1.3;
  margin: 1.6em 0 0.8em;
}
h3 {
  font-size: 0.9em;
  font-weight: normal;
  font-style: normal;
  font-variant: small-caps;
  letter-spacing: 0.06em;
  line-height: 1.3;
  margin: 1.2em 0 0.6em;
}
h4 { font-size: 1em; font-weight: bold; font-style: italic; margin: 1.2em 0 0.3em; }
h5, h6 { font-size: 0.95em; font-style: italic; margin: 1em 0 0.3em; }

/* Paragraphs — indent only, zero inter-paragraph space */
p { margin: 0; text-align: justify; hyphens: auto; }
p + p { text-indent: 1.4em; }
/* Only h1 (chapter title) suppresses indent on the following paragraph;
   subheadings (h2-h6) follow with an indented paragraph like surrounding text */
h1 + p,
blockquote + p, figure + p, ul + p, ol + p,
div.chapter > p:first-child { text-indent: 0; }

/* Drop cap only on the first paragraph that follows a chapter title */
div.chapter > h1 + p::first-letter {
  float: left;
  font-size: 3.1em;
  line-height: 0.82;
  margin: 0.06em 0.08em 0 0;
  font-family: "Baskerville", "Hoefler Text", Georgia, serif;
}

/* Links */
a { color: inherit; text-decoration: none; }

/* Images */
/* Page break only when a new chapter heading (h1) begins a spine item */
div.chapter-start { page-break-before: always; }

img {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 1.4em auto;
  page-break-inside: avoid;
}
img:not([style]) { max-height: 3.5in; }
/* Inline images within text (arrows, symbols) — don't block-ify them */
p img { display: inline; vertical-align: middle; margin: 0 0.1em; max-height: 1.8em; }
figure { page-break-inside: avoid; page-break-before: avoid; margin: 1.4em 0; text-align: center; }
/* Figure caption paragraph: space above, caption styling, stays with its figure */
p:has(+ figure) {
  page-break-after: avoid;
  margin-top: 1.4em;
  margin-bottom: 0.3em;
  font-size: 0.82em;
  color: #444;
  text-align: center;
  text-indent: 0 !important;
  font-variant: small-caps;
  letter-spacing: 0.04em;
}
figcaption {
  font-size: 0.82em;
  color: #444;
  margin-top: 0.5em;
  text-align: center;
  font-style: normal;
}

/* Blockquote */
blockquote {
  margin: 1em 1.8em;
  font-size: 0.96em;
  font-style: italic;
  color: #333;
}

/* Code */
code, kbd, samp {
  font-family: "Menlo", "Courier New", monospace;
  font-size: 0.84em;
}
pre {
  font-family: "Menlo", "Courier New", monospace;
  font-size: 0.82em;
  background: #f7f7f7;
  border-left: 2pt solid #ccc;
  padding: 0.8em 1em;
  page-break-inside: avoid;
  margin: 1.2em 0;
  white-space: pre-wrap;
  word-break: break-all;
}
pre code { font-size: inherit; }

/* Tables — booktabs style: horizontal rules only, no grid */
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82em;
  line-height: 1.3;
  margin: 1.5em 0;
  page-break-inside: avoid;
}
thead tr:first-child th { border-top: 1.5pt solid #222; }
thead tr:last-child  th { border-bottom: 0.75pt solid #555; }
tbody tr:last-child  td { border-bottom: 1.5pt solid #222; }
th, td { padding: 0.28em 0.7em; text-align: left; vertical-align: top; border: none; }
th { font-weight: normal; font-variant: small-caps; letter-spacing: 0.04em; }

/* Lists */
ul, ol { margin: 0.6em 0 0.6em 1.8em; }
li { margin-bottom: 0.15em; }
li p { text-indent: 0; margin: 0; }

/* Horizontal rule → ornamental section break */
hr { border: none; margin: 1.8em 0; text-align: center; }
hr::after { content: "✦"; color: #bbb; font-size: 0.85em; letter-spacing: 0.4em; }

/* Superscripts / footnote markers — small, tight, don't disrupt line height */
sup, sub {
  font-size: 0.65em;
  line-height: 0;
  position: relative;
  vertical-align: baseline;
}
sup { top: -0.5em; }
sub { bottom: -0.3em; }

/* Footnotes */
.footnote, .footnotes {
  font-size: 0.83em;
  color: #555;
  border-top: 0.5pt solid #ccc;
  margin-top: 2em;
  padding-top: 0.6em;
}
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


def check_deps(use_cv: bool, use_sr: bool) -> tuple[bool, bool]:
    """Check deps; return (cv_available, sr_available)."""
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

    # Pillow + numpy are shared by both CV and SR
    pil_ok = True
    if use_cv or use_sr:
        try:
            import PIL  # noqa: F401
        except ImportError:
            print("warning: Pillow not installed — CV/SR disabled (pip install Pillow)", file=sys.stderr)
            pil_ok = False

    numpy_ok = True
    if use_sr and pil_ok:
        try:
            import numpy  # noqa: F401
        except ImportError:
            print("warning: numpy not installed — SR disabled (pip install numpy)", file=sys.stderr)
            numpy_ok = False

    cv_ok = False
    if use_cv and pil_ok:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            cv_ok = True
        except Exception:
            print("warning: pytesseract/Tesseract not available — CV sizing disabled\n"
                  "         pip install pytesseract  &&  brew install tesseract", file=sys.stderr)

    sr_ok = use_sr and pil_ok and numpy_ok
    return cv_ok, sr_ok


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

    # Manifest: collect HTML spine items and CSS files
    manifest: dict[str, Path] = {}
    css_paths: list[Path] = []
    for item in tree.findall(".//opf:item", ns):
        iid = item.get("id", "")
        href = item.get("href", "")
        mt   = item.get("media-type", "")
        if href and ("html" in mt or "xhtml" in mt):
            manifest[iid] = opf_dir / unquote(href)
        elif href and mt == "text/css":
            p = opf_dir / unquote(href)
            if p.exists():
                css_paths.append(p)

    # Spine order
    spine: list[Path] = []
    for itemref in tree.findall(".//opf:itemref", ns):
        idref = itemref.get("idref", "")
        if idref in manifest:
            p = manifest[idref]
            if p.exists():
                spine.append(p)

    return meta, spine, css_paths


def build_heading_class_map(css_paths: list[Path]) -> dict[str, str]:
    """Parse EPUB CSS files; return {class_name: 'h1'|'h2'} for <p> classes that are
    visually headings: large font-size AND a heading-related class name.
    Pure size (dropcap, big, etc.) without a semantic name is excluded."""
    import re
    # Class name must contain a heading-related word to qualify.
    _HEADING_NAME = re.compile(
        r'(?:^|[-_\d])(?:head|title|chapter|section|heading)(?:[-_\d]|$)',
        re.IGNORECASE,
    )

    class_sizes: dict[str, float] = {}
    for css_path in css_paths:
        try:
            css = css_path.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'\.([\w-]+)\s*\{([^}]+)\}', css):
                cls, props = m.group(1), m.group(2)
                if not _HEADING_NAME.search(cls):
                    continue  # not a semantic heading class
                fs = re.search(r'font-size:\s*([\d.]+)em', props)
                if fs:
                    size = float(fs.group(1))
                    if size > class_sizes.get(cls, 0):
                        class_sizes[cls] = size
        except Exception:
            pass

    heading_map: dict[str, str] = {}
    for cls, size in class_sizes.items():
        if size >= 1.3:
            heading_map[cls] = "h1"
        elif size >= 1.1:
            heading_map[cls] = "h2"
    return heading_map


def cv_image_width(img_path: Path) -> str | None:
    """OCR one image; return CSS width string scaled so labels read at TARGET_LABEL_PT, or None."""
    try:
        from PIL import Image
        import pytesseract

        img = Image.open(img_path).convert("RGB")
        W, H = img.size

        def _clamp_dims(w_in: float) -> float:
            w_in = min(w_in, CONTENT_WIDTH_IN * 0.95)
            h_in = w_in * H / W
            if h_in > 3.0:           # never taller than 3in regardless of width
                w_in = 3.0 * W / H
            return max(w_in, 0.5)

        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        heights = [
            h for h, conf, text in zip(data["height"], data["conf"], data["text"])
            if isinstance(conf, (int, float)) and conf > 60   # 60 filters handwriting noise
            and isinstance(text, str) and text.strip()
            and h > 5
        ]

        if not heights:
            # No text detected — size by native pixel dimensions at assumed 150 DPI,
            # capped at 2.5in tall so pure-diagram images don't fill the page.
            w_in = W / 150
            h_in = H / 150
            if h_in > 2.5:
                w_in = 2.5 * W / H
            return f"{_clamp_dims(w_in):.3f}in"

        heights.sort()
        char_h_px = heights[len(heights) // 2]   # median detected text height
        target_w = (W / char_h_px) * (TARGET_LABEL_PT / 72)
        return f"{_clamp_dims(target_w):.3f}in"
    except Exception:
        return None


def is_formula_image(img: "Image.Image") -> bool:  # type: ignore[name-defined]
    """Return True if image looks like an inline formula: small AND near-grayscale."""
    import numpy as np
    _, h = img.size
    if h > SR_MAX_HEIGHT_PX:
        return False
    rgb = np.array(img.convert("RGB"), dtype=np.float32)
    max_c = rgb.max(axis=2)
    min_c = rgb.min(axis=2)
    with np.errstate(divide="ignore", invalid="ignore"):
        sat = np.where(max_c > 0, (max_c - min_c) / max_c, 0.0)
    return float(sat.std()) < SR_MAX_SAT_STD


def upscale_formulas(image_paths: list[Path]) -> dict[Path, tuple[int, int]]:
    """Upscale formula images in-place (Lanczos ×SR_SCALE).
    Returns {path: (original_W, original_H)} for every image that was upscaled."""
    from PIL import Image
    originals: dict[Path, tuple[int, int]] = {}
    n = len(image_paths)
    for i, p in enumerate(image_paths, 1):
        print(f"  SR  {i}/{n}: {p.name:<40}", end="\r", flush=True)
        try:
            img = Image.open(p)
            if is_formula_image(img):
                w, h = img.size
                originals[p] = (w, h)
                upscaled = img.convert("L").resize(
                    (w * SR_SCALE, h * SR_SCALE), Image.LANCZOS
                )
                upscaled.save(p)
        except Exception:
            pass
    if n:
        print()
    return originals


def collect_image_paths(spine: list[Path]) -> list[Path]:
    """Return all unique image paths referenced in spine HTML files, in order."""
    from bs4 import BeautifulSoup
    seen: set[Path] = set()
    result: list[Path] = []
    for html_path in spine:
        try:
            soup = BeautifulSoup(html_path.read_bytes(), "lxml")
            for tag in soup.find_all("img"):
                src = tag.get("src", "")
                if src and not src.startswith(("http://", "https://", "data:")):
                    resolved = (html_path.parent / unquote(src)).resolve()
                    if resolved.exists() and resolved not in seen:
                        seen.add(resolved)
                        result.append(resolved)
        except Exception:
            pass
    return result


def run_ocr(
    image_paths: list[Path],
    formula_originals: dict[Path, tuple[int, int]] | None = None,
) -> dict[Path, str | None]:
    """Compute CSS widths for all images in parallel (one thread per CPU core).
    Formula images use DPI-based sizing; all others go through pytesseract OCR.
    ThreadPoolExecutor is used because pytesseract spawns external processes,
    releasing the GIL and making parallelism effective without pickle overhead."""
    import os
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _size_one(p: Path) -> tuple[Path, str | None]:
        if formula_originals and p in formula_originals:
            orig_w, orig_h = formula_originals[p]
            h_in = orig_h / FORMULA_DPI
            w_in = orig_w / FORMULA_DPI
            h_in = min(max(h_in, 0.15), 0.8)
            w_in = min(w_in * (h_in / (orig_h / FORMULA_DPI)), CONTENT_WIDTH_IN * 0.6)
            return p, f"{w_in:.3f}in"
        return p, cv_image_width(p)

    n = len(image_paths)
    sizes: dict[Path, str | None] = {}
    workers = min(os.cpu_count() or 4, n or 1)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_size_one, p): p for p in image_paths}
        done = 0
        for fut in as_completed(futures):
            done += 1
            print(f"  OCR {done}/{n}", end="\r", flush=True)
            p, result = fut.result()
            sizes[p] = result
    if n:
        print()
    return sizes


def has_chapter_heading(html_path: Path,
                         heading_map: dict[str, str] | None = None) -> bool:
    """Return True if this spine item opens with an h1 (i.e. starts a new chapter).
    heading_map accounts for EPUBs that use <p class="..."> instead of <h1>.
    Skips wrapper divs and looks at the first few block elements."""
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html_path.read_bytes(), "lxml")
        body = soup.find("body")
        if not body:
            return False
        checked = 0
        for el in body.find_all(["h1", "p"]):
            if not el.get_text(strip=True):
                continue
            if el.name == "h1":
                return True
            if heading_map:
                cls = next(iter(el.get("class", [])), "")
                if heading_map.get(cls) == "h1":
                    return True
            checked += 1
            if checked >= 3:  # chapter number + title = 2 elements max before giving up
                return False
        return False
    except Exception:
        return False


def chapter_body(html_path: Path, cv_sizes: dict[Path, str | None] | None = None,
                 new_chapter: bool = False,
                 heading_map: dict[str, str] | None = None) -> str:
    """Return the inner body content of a chapter with absolute image paths."""
    from bs4 import BeautifulSoup

    raw = html_path.read_bytes()
    # Always use lxml (HTML mode) — lxml-xml would preserve XHTML self-closing
    # non-void elements like <em/> which Chromium HTML5 mode treats as an
    # unclosed opening tag, cascading italic/bold to end of document.
    try:
        soup = BeautifulSoup(raw, "lxml")
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

    # Remove embedded EPUB stylesheets — our CSS takes over entirely
    for tag in soup.find_all(["style", "link"]):
        tag.decompose()

    # Strip inline styles and size attrs that fight our CSS
    for tag in soup.find_all(True):
        tag.attrs.pop("style", None)
        tag.attrs.pop("color", None)
    for tag in soup.find_all(["table", "thead", "tbody", "tfoot", "tr", "th", "td",
                               "img", "figure", "svg", "col", "colgroup"]):
        tag.attrs.pop("width", None)
        tag.attrs.pop("height", None)

    # Remap <p> tags that the EPUB CSS styled as headings (large font-size) to real h1/h2/h3.
    # This fixes Calibre-exported EPUBs that use <p class="Chapter-Title"> instead of <h1>.
    if heading_map:
        for p_tag in soup.find_all("p"):
            for cls in p_tag.get("class", []):
                if cls in heading_map:
                    p_tag.name = heading_map[cls]
                    break

    # Promote image-only <p> and <div> wrappers to <figure> so they stay block/centered.
    # This also makes p:has(+ figure) CSS work for figure captions that precede the image.
    # Leaves elements that mix text + images alone (those images become inline via CSS).
    for tag in soup.find_all(["p", "div"]):
        if tag.find("img") and not tag.get_text(strip=True):
            tag.name = "figure"

    # Apply CV-computed widths as inline styles (after all stripping)
    if cv_sizes:
        for tag in soup.find_all("img"):
            src = tag.get("src", "")
            if src.startswith("file://"):
                img_path = Path(unquote(urlparse(src).path))
                w = cv_sizes.get(img_path)
                if w:
                    tag["style"] = f"width: {w}; height: auto;"

    body = soup.find("body")
    raw_html = body.decode_contents() if body else str(soup)
    cls = "chapter chapter-start" if new_chapter else "chapter"
    return f'<div class="{cls}">\n{raw_html}\n</div>'


def _clean_title(title: str) -> str:
    """Strip trailing parenthesized codes (ISBNs, etc.) from EPUB title strings."""
    import re
    return re.sub(r'\s*\([0-9X\-]{8,}\)\s*$', '', title).strip()


def render_pdf(html_path: Path, pdf_path: Path, title: str = "") -> None:
    from playwright.sync_api import sync_playwright

    display_title = _clean_title(title)
    _style = "font-family:Georgia,serif;color:#aaa;width:100%;padding:0 1.15in;"
    header = (
        f'<div style="{_style}font-size:8pt;font-style:italic;text-align:center;">'
        f'{display_title}</div>'
    )
    footer = (
        f'<div style="{_style}font-size:9pt;text-align:center;">'
        '<span class="pageNumber"></span></div>'
    )

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.as_uri(), wait_until="networkidle")
        page.pdf(
            path=str(pdf_path),
            width=PAGE_WIDTH,
            height=PAGE_HEIGHT,
            print_background=True,
            display_header_footer=True,
            header_template=header,
            footer_template=footer,
            margin={"top": "0.82in", "right": "1.15in", "bottom": "0.72in", "left": "1.15in"},
        )
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert EPUB to PDF for iPad Pro.")
    ap.add_argument("epub",   type=Path, help="Input .epub file")
    ap.add_argument("output", type=Path, nargs="?", help="Output .pdf (default: same stem as input)")
    ap.add_argument("--no-cv", action="store_false", dest="use_cv",
                    help="Disable OCR-based image sizing (faster, uses fixed max-height fallback)")
    ap.add_argument("--no-sr", action="store_false", dest="use_sr",
                    help="Disable super-resolution upscaling of formula images")
    args = ap.parse_args()

    use_cv, use_sr = check_deps(args.use_cv, args.use_sr)

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
        meta, spine, css_paths = parse_opf(opf_path)

        if not spine:
            die("No readable chapters found in EPUB spine.")

        print(f"  Title   : {meta.get('title', '(unknown)')}")
        if meta.get("creator"):
            print(f"  Author  : {meta['creator']}")
        print(f"  Chapters: {len(spine)}")

        cv_sizes: dict[Path, str | None] | None = None
        if use_cv or use_sr:
            image_paths = collect_image_paths(spine)
            print(f"Found {len(image_paths)} unique images")

            formula_originals: dict[Path, tuple[int, int]] = {}
            if use_sr and image_paths:
                print("Super-resolving formula images …")
                formula_originals = upscale_formulas(image_paths)
                print(f"  Upscaled {len(formula_originals)}/{len(image_paths)} formula images {SR_SCALE}×")

            if use_cv and image_paths:
                print("OCR-sizing images …")
                cv_sizes = run_ocr(image_paths, formula_originals or None)
                sized = sum(1 for v in cv_sizes.values() if v)
                print(f"  Sized {sized}/{len(image_paths)} via OCR ({len(image_paths)-sized} fallback)")

        heading_map = build_heading_class_map(css_paths)
        if heading_map:
            print(f"  Heading classes: {', '.join(sorted(heading_map))}")

        print("Building merged HTML …")
        chapters = [
            chapter_body(p, cv_sizes=cv_sizes,
                         new_chapter=has_chapter_heading(p, heading_map),
                         heading_map=heading_map)
            for p in spine
        ]
        html = HTML_TEMPLATE.format(
            lang=meta.get("language", "en"),
            title=meta.get("title", epub_path.stem),
            css=PAGE_CSS,
            body="\n".join(chapters),
        )

        html_file = tmp / "_merged.html"
        html_file.write_text(html, encoding="utf-8")

        print("Rendering PDF via Chromium …")
        render_pdf(html_file, pdf_path, title=meta.get("title", epub_path.stem))

    print(f"\nDone → {pdf_path}")


if __name__ == "__main__":
    main()
