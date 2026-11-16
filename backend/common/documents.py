# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Extract plain text from uploaded documents for the AI features.

Supports PDF (pypdf) and presentations (PPTX via python-pptx, ODP via odfpy).
The text keeps the document's structure (#305): every page/slide starts with
a marker line (``=== Seite N ===`` for PDF, ``=== Folie N ===`` for
presentations), line breaks survive (only runs of spaces within a line are
collapsed), tables come row by row as ``Zelle | Zelle | …`` lines, charts as
their title plus the plotted values, and speaker notes are labelled
``Sprechernotizen:``. The result is truncated to ``max_chars`` so the prompt
(and cost) stays bounded. No OCR — image-only files raise
``DocumentTextError``.

Each extractor also returns the document's page/slide count (>= 1) so the
"questions per page" setting of AI generation can size the run."""
import logging
import re

logger = logging.getLogger(__name__)

MAX_CHARS = 12000

PAGE_LABEL_PDF = "Seite"
PAGE_LABEL_SLIDE = "Folie"
# A marker line opening each page/slide in the extracted text; the
# generation pipeline splits on it (rooms.generation).
PAGE_MARKER_RE = re.compile(r"^=== (Folie|Seite) (\d+) ===$", re.MULTILINE)

_INLINE_SPACE = re.compile(r"[^\S\n]+")  # whitespace except newlines
_BLANK_LINES = re.compile(r"\n{3,}")


class DocumentTextError(Exception):
    """The document could not be turned into usable text."""


def page_marker(label, number):
    return f"=== {label} {number} ==="


def _clean(text):
    """Collapse runs of spaces/tabs within lines, trim every line and keep at
    most one blank line in a row — line breaks themselves survive."""
    lines = [_INLINE_SPACE.sub(" ", line).strip() for line in (text or "").split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _assemble(pages, label, max_chars):
    """Join per-page texts with marker lines. Empty pages are left out but
    keep their real number (so "Folie 5" is the fifth slide). Raises
    DocumentTextError when no page has any text."""
    parts = []
    for number, text in enumerate(pages, start=1):
        body = _clean(text)
        if body:
            parts.append(f"{page_marker(label, number)}\n{body}")
    if not parts:
        raise DocumentTextError("Kein extrahierbarer Text (evtl. gescanntes PDF).")
    return "\n\n".join(parts)[:max_chars]


def _one_line(text):
    return " ".join(str(text or "").split())


def _table_lines(rows):
    """Rows (lists of cell texts) as ``a | b | c`` lines under a "Tabelle:"
    label; the first row is the header. Empty rows are dropped."""
    lines = []
    for row in rows:
        cells = [_one_line(c) for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return ["Tabelle:", *lines] if lines else []


def _format_value(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _one_line(value)


def _chart_lines(title, categories, series):
    """``Diagramm: <title>`` followed by one ``Serie: Kat=Wert, …`` line per
    series. ``series`` is a list of (name, values)."""
    lines = [f"Diagramm: {_one_line(title)}".rstrip()]
    for name, values in series:
        pairs = []
        for index, value in enumerate(values):
            if value is None:
                continue
            category = _one_line(categories[index]) if index < len(categories) else ""
            shown = _format_value(value)
            pairs.append(f"{category}={shown}" if category else shown)
        if pairs:
            lines.append(f"{_one_line(name) or 'Serie'}: {', '.join(pairs)}")
    return lines


def extract_pdf_text(file, *, max_chars=MAX_CHARS):
    from pypdf import PdfReader

    try:
        reader = PdfReader(file)
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # pypdf raises a variety of errors on bad input
        raise DocumentTextError(str(exc)) from exc
    return _assemble(pages, PAGE_LABEL_PDF, max_chars), max(1, len(pages))


# --- PPTX -----------------------------------------------------------------

def _pptx_chart_lines(chart):
    title = ""
    if chart.has_title and chart.chart_title.has_text_frame:
        title = chart.chart_title.text_frame.text
    categories, series = [], []
    for plot in chart.plots:
        try:
            plot_categories = [str(c) for c in plot.categories]
        except Exception:  # e.g. XY/bubble charts have no category axis
            logger.info("PPTX chart plot without categories", exc_info=True)
            plot_categories = []
        categories = categories or plot_categories
        for item in plot.series:
            try:
                values = list(item.values)
            except Exception:
                logger.info("Skipping an unreadable PPTX chart series", exc_info=True)
                continue
            series.append((item.name, values))
    return _chart_lines(title, categories, series)


def _pptx_shape_lines(shape):
    """Text of one shape (recursing into groups); never raises."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    lines = []
    try:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            for child in shape.shapes:
                lines.extend(_pptx_shape_lines(child))
            return lines
        if shape.has_text_frame:
            lines.append(shape.text_frame.text)
        if getattr(shape, "has_table", False) and shape.has_table:
            lines.extend(
                _table_lines([cell.text for cell in row.cells] for row in shape.table.rows)
            )
        if getattr(shape, "has_chart", False) and shape.has_chart:
            lines.extend(_pptx_chart_lines(shape.chart))
    except Exception:  # one odd shape must not fail the whole document
        logger.info("Skipping an unreadable PPTX shape", exc_info=True)
    return lines


def _pptx_notes(slide):
    try:
        if slide.has_notes_slide:  # .notes_slide would create one otherwise
            frame = slide.notes_slide.notes_text_frame
            if frame is not None and frame.text.strip():
                return f"Sprechernotizen: {frame.text.strip()}"
    except Exception:
        logger.info("Skipping unreadable PPTX speaker notes", exc_info=True)
    return ""


def extract_pptx_text(file, *, max_chars=MAX_CHARS):
    from pptx import Presentation

    try:
        presentation = Presentation(file)
        pages = []
        for slide in presentation.slides:
            lines = []
            for shape in slide.shapes:
                lines.extend(_pptx_shape_lines(shape))
            notes = _pptx_notes(slide)
            if notes:
                lines.append(notes)
            pages.append("\n".join(lines))
    except Exception as exc:
        raise DocumentTextError(str(exc)) from exc
    return _assemble(pages, PAGE_LABEL_SLIDE, max_chars), max(1, len(pages))


# --- ODP ------------------------------------------------------------------

_NS_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_NS_DRAW = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
_NS_PRESENTATION = "urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"
_NS_CHART = "urn:oasis:names:tc:opendocument:xmlns:chart:1.0"
_NS_XLINK = "http://www.w3.org/1999/xlink"


def _odf_children(node):
    return [c for c in getattr(node, "childNodes", []) if hasattr(c, "qname")]


def _odf_find(node, qname):
    """All descendants of ``node`` with this qname (depth-first)."""
    found = []
    for child in _odf_children(node):
        if child.qname == qname:
            found.append(child)
        found.extend(_odf_find(child, qname))
    return found


def _odf_table_rows(table):
    from odf import teletype

    rows = []
    for row in _odf_find(table, (_NS_TABLE, "table-row")):
        cells = [
            c for c in _odf_children(row)
            if c.qname == (_NS_TABLE, "table-cell")
        ]
        rows.append(
            [" ".join(teletype.extractText(p) for p in _odf_children(c)) for c in cells]
        )
    return rows


def _odp_chart_lines(chart_doc):
    """Title and values of an embedded ODF chart (its local data table:
    first row = series names, first column = categories)."""
    from odf import teletype

    body = chart_doc.topnode
    title = ""
    for node in _odf_find(body, (_NS_CHART, "title")):
        title = " ".join(teletype.extractText(p) for p in _odf_children(node))
        break
    tables = _odf_find(body, (_NS_TABLE, "table"))
    if not tables:
        return [f"Diagramm: {_one_line(title)}".rstrip()] if title else []
    rows = _odf_table_rows(tables[0])
    if not rows:
        return []
    header, data = rows[0], rows[1:]
    categories = [r[0] if r else "" for r in data]
    series = []
    for col in range(1, len(header)):
        values = [r[col] if col < len(r) and r[col] != "" else None for r in data]
        series.append((header[col], values))
    return _chart_lines(title, categories, series)


def _odp_walk(node, lines, notes, charts, in_notes=False):
    """Collect a slide's text: paragraphs/headings as lines, tables row by
    row, embedded charts, and speaker notes separately — without counting
    table-cell or notes paragraphs twice."""
    from odf import teletype

    for child in _odf_children(node):
        qname = child.qname
        if qname == (_NS_PRESENTATION, "notes"):
            _odp_walk(child, notes, notes, charts, in_notes=True)
        elif qname == (_NS_TABLE, "table"):
            lines.extend(_table_lines(_odf_table_rows(child)))
        elif qname in ((_NS_TEXT, "p"), (_NS_TEXT, "h")):
            lines.append(teletype.extractText(child))
        elif qname == (_NS_DRAW, "object") and not in_notes:
            href = (child.getAttrNS(_NS_XLINK, "href") or "").rstrip("/")
            chart_doc = charts.get(href.lstrip("./"))
            if chart_doc is not None:
                try:
                    lines.extend(_odp_chart_lines(chart_doc))
                except Exception:
                    logger.info("Skipping an unreadable ODP chart", exc_info=True)
        else:
            _odp_walk(child, lines, notes, charts, in_notes)


def extract_odp_text(file, *, max_chars=MAX_CHARS):
    from odf.draw import Page
    from odf.opendocument import load

    try:
        document = load(file)
        # Embedded objects (charts) are loaded as child documents whose
        # folder ("/Object 1") matches the frame's xlink:href ("./Object 1").
        charts = {
            str(getattr(child, "folder", "")).lstrip("/"): child
            for child in getattr(document, "childobjects", [])
            if "chart" in str(getattr(child, "mimetype", ""))
        }
        pages = []
        for page in document.getElementsByType(Page):
            lines, notes = [], []
            try:
                _odp_walk(page, lines, notes, charts)
            except Exception:
                logger.info("Skipping unreadable ODP slide content", exc_info=True)
            note_text = " ".join(_one_line(n) for n in notes if n.strip())
            if note_text:
                lines.append(f"Sprechernotizen: {note_text}")
            pages.append("\n".join(lines))
    except Exception as exc:
        raise DocumentTextError(str(exc)) from exc
    return _assemble(pages, PAGE_LABEL_SLIDE, max_chars), max(1, len(pages))


_EXTRACTORS = {
    ".pdf": extract_pdf_text,
    ".pptx": extract_pptx_text,
    ".odp": extract_odp_text,
}


def extract_document(file, filename, *, max_chars=MAX_CHARS):
    """Dispatch on the file extension. Returns (text, pages) with pages >= 1;
    the text carries page/slide marker lines (see module docstring).
    Raises DocumentTextError for an unsupported type or unreadable/scanned
    file."""
    name = (filename or "").lower()
    for suffix, extractor in _EXTRACTORS.items():
        if name.endswith(suffix):
            return extractor(file, max_chars=max_chars)
    raise DocumentTextError(
        "Nicht unterstütztes Format. Erlaubt sind PDF, PPTX und ODP."
    )


def extract_text(file, filename, *, max_chars=MAX_CHARS):
    """Dispatch on the file extension. Raises DocumentTextError for an
    unsupported type or an unreadable/scanned file."""
    return extract_document(file, filename, max_chars=max_chars)[0]
