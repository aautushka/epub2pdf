"""Unit tests for epub2pdf.py — pure functions that don't require Playwright or real EPUBs."""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
import epub2pdf


# ---------------------------------------------------------------------------
# _clean_title
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("My Book (9781234567890)", "My Book"),
    ("Normal Title", "Normal Title"),
    ("Title (978-0-00-000000-0)", "Title"),
    ("My Book (2024)", "My Book (2024)"),          # short code, kept
    ("Title (ABCD-1234)", "Title (ABCD-1234)"),    # not ISBN-like, kept
    ("  Spaces  (9780000000000)  ", "Spaces"),
])
def test_clean_title(raw, expected):
    assert epub2pdf._clean_title(raw) == expected


# ---------------------------------------------------------------------------
# get_spine_item_image
# ---------------------------------------------------------------------------

def _write_html(path: Path, body: str, head: str = "") -> None:
    path.write_text(
        f"<html><head>{head}</head><body>{body}</body></html>",
        encoding="utf-8",
    )


def test_get_spine_item_image_standard_img(tmp_path):
    img = tmp_path / "cover.jpg"
    img.write_bytes(b"x")
    html = tmp_path / "cover.xhtml"
    _write_html(html, '<img src="cover.jpg"/>')
    assert epub2pdf.get_spine_item_image(html) == img.resolve()


def test_get_spine_item_image_img_in_div(tmp_path):
    """Image wrapped in a div should still be detected."""
    img = tmp_path / "cover.jpg"
    img.write_bytes(b"x")
    html = tmp_path / "cover.xhtml"
    _write_html(html, '<div id="cover"><img src="cover.jpg"/></div>')
    assert epub2pdf.get_spine_item_image(html) == img.resolve()


def test_get_spine_item_image_svg_calibre(tmp_path):
    """Calibre's SVG cover pattern: <svg><image xlink:href="..."/></svg>."""
    img = tmp_path / "cover.jpeg"
    img.write_bytes(b"x")
    html = tmp_path / "titlepage.xhtml"
    _write_html(
        html,
        '<div><svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<image width="398" height="600" xlink:href="cover.jpeg"/>'
        "</svg></div>",
    )
    assert epub2pdf.get_spine_item_image(html) == img.resolve()


def test_get_spine_item_image_with_body_text(tmp_path):
    """Page with real text content → not a fullbleed candidate."""
    img = tmp_path / "img.jpg"
    img.write_bytes(b"x")
    html = tmp_path / "ch.xhtml"
    _write_html(html, '<p>Some text</p><img src="img.jpg"/>')
    assert epub2pdf.get_spine_item_image(html) is None


def test_get_spine_item_image_title_tag_ignored(tmp_path):
    """<title> text in <head> must not be mistaken for body text."""
    img = tmp_path / "cover.jpg"
    img.write_bytes(b"x")
    html = tmp_path / "cover.xhtml"
    _write_html(html, '<img src="cover.jpg"/>', head="<title>Cover</title>")
    assert epub2pdf.get_spine_item_image(html) == img.resolve()


def test_get_spine_item_image_multiple_imgs(tmp_path):
    """Two images → not a fullbleed page."""
    for name in ("a.jpg", "b.jpg"):
        (tmp_path / name).write_bytes(b"x")
    html = tmp_path / "ch.xhtml"
    _write_html(html, '<img src="a.jpg"/><img src="b.jpg"/>')
    assert epub2pdf.get_spine_item_image(html) is None


def test_get_spine_item_image_no_images(tmp_path):
    html = tmp_path / "ch.xhtml"
    _write_html(html, "<p>Text only</p>")
    assert epub2pdf.get_spine_item_image(html) is None


def test_get_spine_item_image_returns_path_even_if_missing(tmp_path):
    """Returns the resolved path even if the image file doesn't exist yet;
    segment_spine is responsible for the .exists() check."""
    html = tmp_path / "cover.xhtml"
    _write_html(html, '<img src="missing.jpg"/>')
    result = epub2pdf.get_spine_item_image(html)
    assert result is not None
    assert result.name == "missing.jpg"


# ---------------------------------------------------------------------------
# segment_spine
# ---------------------------------------------------------------------------

def _content_html(path: Path) -> Path:
    path.write_text("<html><body><p>Text</p></body></html>", encoding="utf-8")
    return path


def _image_html(path: Path, img_path: Path) -> Path:
    path.write_text(
        f'<html><body><img src="{img_path.name}"/></body></html>',
        encoding="utf-8",
    )
    return path


def test_segment_spine_all_content(tmp_path):
    ch1 = _content_html(tmp_path / "ch1.xhtml")
    ch2 = _content_html(tmp_path / "ch2.xhtml")
    segs = epub2pdf.segment_spine([ch1, ch2])
    assert segs == [("content", [ch1, ch2])]


def test_segment_spine_leading_fullbleed(tmp_path):
    img = tmp_path / "cover.jpg"; img.write_bytes(b"x")
    cover = _image_html(tmp_path / "cover.xhtml", img)
    ch = _content_html(tmp_path / "ch.xhtml")
    segs = epub2pdf.segment_spine([cover, ch])
    assert len(segs) == 2
    assert segs[0] == ("fullbleed", [img.resolve()])
    assert segs[1] == ("content", [ch])


def test_segment_spine_multiple_leading_fullbleed(tmp_path):
    img1 = tmp_path / "cover.jpg"; img1.write_bytes(b"x")
    img2 = tmp_path / "title.jpg"; img2.write_bytes(b"x")
    cover = _image_html(tmp_path / "cover.xhtml", img1)
    title = _image_html(tmp_path / "title.xhtml", img2)
    ch = _content_html(tmp_path / "ch.xhtml")
    segs = epub2pdf.segment_spine([cover, title, ch])
    assert segs[0] == ("fullbleed", [img1.resolve(), img2.resolve()])
    assert segs[1] == ("content", [ch])


def test_segment_spine_mid_book_fullbleed(tmp_path):
    """Image-only page in the middle splits into three segments."""
    img = tmp_path / "map.jpg"; img.write_bytes(b"x")
    ch1 = _content_html(tmp_path / "ch1.xhtml")
    map_page = _image_html(tmp_path / "map.xhtml", img)
    ch2 = _content_html(tmp_path / "ch2.xhtml")
    segs = epub2pdf.segment_spine([ch1, map_page, ch2])
    assert len(segs) == 3
    assert segs[0] == ("content", [ch1])
    assert segs[1] == ("fullbleed", [img.resolve()])
    assert segs[2] == ("content", [ch2])


def test_segment_spine_all_fullbleed(tmp_path):
    img1 = tmp_path / "a.jpg"; img1.write_bytes(b"x")
    img2 = tmp_path / "b.jpg"; img2.write_bytes(b"x")
    p1 = _image_html(tmp_path / "p1.xhtml", img1)
    p2 = _image_html(tmp_path / "p2.xhtml", img2)
    segs = epub2pdf.segment_spine([p1, p2])
    assert segs == [("fullbleed", [img1.resolve(), img2.resolve()])]


def test_segment_spine_image_not_on_disk(tmp_path):
    """If image file doesn't exist, the page is treated as content (safe fallback)."""
    html = tmp_path / "cover.xhtml"
    _write_html(html, '<img src="missing.jpg"/>')
    segs = epub2pdf.segment_spine([html])
    assert segs == [("content", [html])]
