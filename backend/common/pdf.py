# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Generic PDF frame for downloadable documents (reportlab, built-in Helvetica).

Deliberately free of app imports (only Django, stdlib and reportlab): it is meant to move into
the shared basicbar packages later (ADR-0008).
"""
import re
from collections.abc import Callable
from html.parser import HTMLParser
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils.translation import gettext as _
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm as MM
from reportlab.pdfgen import canvas
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

MARGIN = 20 * MM
BOTTOM = 18 * MM
MAX_HEADING_CHARS = 300  # longer "headings" are body text: keepWithNext on a block taller than a page hangs the build
INLINE_TAGS = {"strong": "b", "b": "b", "em": "i", "i": "i", "u": "u", "s": "strike", "del": "strike",
               "strike": "strike"}
HEADINGS = {"h1": "h1", "h2": "h2", "h3": "h3"}
SKIP_CONTENT = {"script", "style"}
TABLE_TAGS = {"table", "thead", "tbody", "tfoot", "tr"}


def safe_text(text: str) -> str:
    """Helvetica covers WinAnsi (cp1252) only; everything else becomes "?"."""
    return str(text).encode("cp1252", errors="replace").decode("cp1252")


def _markup(text: str) -> str:
    return escape(safe_text(text)).replace("\n", "<br/>")


def make_styles() -> dict:
    base = getSampleStyleSheet()["Normal"]
    normal = ParagraphStyle("n", parent=base, fontName="Helvetica", fontSize=10, leading=13.5, spaceAfter=3)
    styles = {
        "normal": normal,
        "small": ParagraphStyle("s", parent=normal, fontSize=8.5, leading=11),
        "bold": ParagraphStyle("b", parent=normal, fontName="Helvetica-Bold"),
        "muted": ParagraphStyle("m", parent=normal, fontSize=8.5, leading=11, textColor=colors.HexColor("#666666")),
        "h1": ParagraphStyle("h1", parent=normal, fontName="Helvetica-Bold", fontSize=18, leading=22,
                             spaceBefore=4, spaceAfter=6, keepWithNext=1),
        "h2": ParagraphStyle("h2", parent=normal, fontName="Helvetica-Bold", fontSize=15, leading=18,
                             spaceBefore=14, spaceAfter=5, keepWithNext=1),
        "h3": ParagraphStyle("h3", parent=normal, fontName="Helvetica-Bold", fontSize=12, leading=15,
                             spaceBefore=8, spaceAfter=2, keepWithNext=1),
        "quote": ParagraphStyle("q", parent=normal, leftIndent=10, textColor=colors.HexColor("#444444")),
        "cell": ParagraphStyle("c", parent=normal, fontSize=9, leading=11.5, spaceAfter=0),
        "cell_head": ParagraphStyle("ch", parent=normal, fontName="Helvetica-Bold", fontSize=9, leading=11.5,
                                    spaceAfter=0),
    }
    return styles


def _has(styles, key) -> bool:
    try:
        styles[key]
        return True
    except KeyError:
        return False


class _HtmlToFlowables(HTMLParser):
    """Editor HTML (p, br, inline formatting, lists, headings, blockquote) to Paragraphs. Unknown
    tags are dropped, their text kept; the markup passed to reportlab is always balanced."""

    def __init__(self, styles):
        super().__init__(convert_charrefs=True)
        own = make_styles()
        # accept any mapping/stylesheet; keys it lacks fall back to the built-in styles
        self.styles = {key: (styles[key] if _has(styles, key) else own[key]) for key in own}
        self.out = []
        self.buf = ""
        self.open = []          # inline tags currently open (reportlab names)
        self.block = "normal"   # style key of the paragraph being built
        self.lists = []         # stack of [kind, counter]
        self.bullet = None
        self.hrefs = []
        self.skip = 0
        self.has_text = False
        self.cells = 0          # cells already seen in the current table row
        self.pre = 0

    # -- paragraph handling
    def _flush(self):
        if self.has_text:
            closing = "".join(f"</{t}>" for t in reversed(self.open))
            self.out.append(self._paragraph(self.buf + closing))
            # the bullet belongs to the first paragraph of the item only (TipTap: <li><p>..</p></li>)
            self.bullet = None
        self.buf = "".join(f"<{t}>" for t in self.open)
        self.has_text = False

    def _paragraph(self, markup):
        depth = len(self.lists)
        style = self.styles[self.block]
        if self.block in HEADINGS.values() and len(re.sub(r"<[^>]*>", "", markup)) > MAX_HEADING_CHARS:
            style = self.styles["bold"]
        if self.bullet is not None:
            style = ParagraphStyle("li", parent=style, leftIndent=12 * depth + 4, bulletIndent=12 * (depth - 1))
        try:
            return Paragraph(markup, style, bulletText=self.bullet)
        except Exception:  # never let one broken fragment kill the document
            plain = re.sub(r"<[^>]*>", "", markup.replace("<br/>", " "))  # already escaped
            return Paragraph(plain, style, bulletText=self.bullet)

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_CONTENT:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in INLINE_TAGS:
            self.open.append(INLINE_TAGS[tag])
            self.buf += f"<{INLINE_TAGS[tag]}>"
        elif tag == "a":
            self.hrefs.append(dict(attrs).get("href") or "")
        elif tag == "br":
            self.buf += "<br/>"
        elif tag == "img":
            self.buf += escape(_("[Image]"))
            self.has_text = True
        elif tag in ("td", "th"):
            if self.cells:
                self.buf += " | "
            self.cells += 1
        elif tag in TABLE_TAGS:
            self._flush()
            self.cells = 0
        elif tag == "pre":
            self._flush()
            self.pre += 1
        elif tag in ("ul", "ol"):
            self._flush()
            self.lists.append([tag, 0])
        elif tag == "li":
            self._flush()
            if not self.lists:
                self.lists.append(["ul", 0])
            entry = self.lists[-1]
            entry[1] += 1
            self.bullet = f"{entry[1]}." if entry[0] == "ol" else "•"
        elif tag in HEADINGS:
            self._flush()
            self.block = HEADINGS[tag]
        elif tag == "blockquote":
            self._flush()
            self.block = "quote"
        elif tag in ("p", "div"):
            self._flush()

    def handle_endtag(self, tag):
        if tag in SKIP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in INLINE_TAGS:
            name = INLINE_TAGS[tag]
            if name in self.open:
                # close down to the match, reopen the tags in between (keeps markup balanced)
                idx = len(self.open) - 1 - self.open[::-1].index(name)
                inner = self.open[idx + 1:]
                self.buf += "".join(f"</{t}>" for t in reversed(self.open[idx:]))
                self.buf += "".join(f"<{t}>" for t in inner)
                self.open = self.open[:idx] + inner
        elif tag == "a":
            if self.hrefs:
                href = self.hrefs.pop()
                if href:
                    self.buf += escape(safe_text(f" ({href})"))
        elif tag in ("ul", "ol"):
            self._flush()
            self.bullet = None
            if self.lists:
                self.lists.pop()
        elif tag in TABLE_TAGS or tag == "pre":
            self._flush()
            self.cells = 0
            if tag == "pre":
                self.pre = max(0, self.pre - 1)
        elif tag in ("li", "p", "div") or tag in HEADINGS or tag == "blockquote":
            self._flush()
            if tag in HEADINGS or tag == "blockquote":
                self.block = "normal"

    def handle_data(self, data):
        if self.skip:
            return
        if not self.open and not self.buf.strip() and not data.strip():
            return
        if self.pre:
            self.buf += _markup(data)
            if data.strip():
                self.has_text = True
            return
        self.buf += escape(safe_text(data))
        if data.strip():
            self.has_text = True

    def result(self):
        self.close()
        self._flush()
        return self.out


def html_to_flowables(html: str, styles) -> list:
    parser = _HtmlToFlowables(styles)
    parser.feed(html or "")
    return parser.result()


def _numbered_canvas(footer_left: str):
    left = safe_text(footer_left)

    class NumberedCanvas(canvas.Canvas):
        """Two passes: the page count is known only after the last page."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            count = len(self._pages)
            page_label = _("Page %(page)s of %(pages)s")
            for state in self._pages:
                self.__dict__.update(state)
                width, _height = self._pagesize
                self.setFont("Helvetica", 8)
                self.setFillColor(colors.HexColor("#555555"))
                self.drawString(MARGIN, 10 * MM, left)
                self.drawRightString(width - MARGIN, 10 * MM,
                                     safe_text(page_label % {"page": self._pageNumber, "pages": count}))
                super().showPage()
            super().save()

    return NumberedCanvas


class PdfDocument:
    """Collects flowables and renders an A4 document with a numbered footer."""

    def __init__(self, title: str, *, footer_left: str = "", compress: bool = True):
        self.title = title
        self.footer_left = footer_left
        self.compress = compress
        self.styles = make_styles()
        self._story: list = []

    def _add(self, *flowables):
        self._story.extend(flowables)

    def heading(self, text: str, level: int = 1):
        key = f"h{min(max(level, 1), 3)}" if len(str(text)) <= MAX_HEADING_CHARS else "bold"
        self._add(Paragraph(_markup(text), self.styles[key]))

    def paragraph(self, text: str, *, style: str = "normal"):
        self._add(Paragraph(_markup(text), self.styles[style]))

    def rich(self, html: str):
        self._add(*html_to_flowables(html, self.styles))

    def bullets(self, items: list[str]):
        style = ParagraphStyle("bl", parent=self.styles["normal"], leftIndent=16, bulletIndent=4)
        for item in items:
            self._add(Paragraph(_markup(item), style, bulletText="•"))

    def table(self, rows: list[list[str]], *, header: bool = True, col_widths: list[float] | None = None):
        if not rows:
            return
        data = [[Paragraph(_markup(cell), self.styles["cell_head" if header and i == 0 else "cell"])
                 for cell in row] for i, row in enumerate(rows)]
        table = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
        style = [("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c8c8c8")),
                 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")))
        table.setStyle(TableStyle(style))
        self._add(table, Spacer(1, 2 * MM))

    def rule(self):
        """Thin horizontal separator line."""
        self._add(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#c8c8c8"),
                             spaceBefore=2 * MM, spaceAfter=2 * MM))

    def spacer(self, mm: float = 3):
        self._add(Spacer(1, mm * MM))

    def _collect(self, builder: Callable[["PdfDocument"], None]) -> list:
        outer, self._story = self._story, []
        try:
            builder(self)
            return self._story
        finally:
            self._story = outer

    def keep_together(self, builder: Callable[["PdfDocument"], None]):
        self._add(KeepTogether(self._collect(builder)))

    def box(self, builder: Callable[["PdfDocument"], None]):
        """Light grey framed block. Rendered as a one-cell table, so it cannot split across pages."""
        inner = self._collect(builder)
        box = Table([[inner]], colWidths=[A4[0] - 2 * MARGIN])
        if box.wrap(A4[0] - 2 * MARGIN, A4[1])[1] > A4[1] - MARGIN - BOTTOM - 4 * MM:
            self._add(*inner, Spacer(1, 2 * MM))  # too tall for one page: a one-cell table cannot split
            return
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f3f3")),
                                 ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#aaaaaa")),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                 ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        self._add(box, Spacer(1, 2 * MM))

    def render(self) -> bytes:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                                topMargin=MARGIN, bottomMargin=BOTTOM, title=safe_text(self.title),
                                pageCompression=1 if self.compress else 0)
        doc.build(list(self._story), canvasmaker=_numbered_canvas(self.footer_left))
        return buffer.getvalue()
