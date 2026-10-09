"""Small ReportLab toolkit shared by the case report and the draft certificate.

Library: ReportLab (BSD-3-Clause), generation only, fully offline. Output is reproducible:
`invariant=1` fixes the creation date, the document ID and the object ordering inputs, and the
metadata below is constant.

Font: Bitstream Vera Sans (Vera, VeraBd, VeraIt) as shipped inside ReportLab, embedded as TrueType
subsets. Licence: Bitstream Vera Fonts licence (permissive: redistribution and bundling allowed,
the fonts may not be sold by themselves). Coverage is Latin only. Any character the font has no
glyph for is replaced by a visible `[U+XXXX]` marker and counted (see Sanitizer); nothing is
dropped silently.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

__all__ = [
    "KeepTogether", "PageBreak", "Paragraph", "Sanitizer", "Spacer", "Styles", "Table",
    "TableStyle", "build_pdf", "colors", "mm",
]  # fmt: skip

FONT_DIR = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
_REGISTERED = False
CMAP: set[int] = set()


def register_fonts() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    for name, fn in (
        ("Vera", "Vera.ttf"),
        ("Vera-Bold", "VeraBd.ttf"),
        ("Vera-Italic", "VeraIt.ttf"),
    ):
        pdfmetrics.registerFont(TTFont(name, os.path.join(FONT_DIR, fn)))
    pdfmetrics.registerFontFamily(
        "Vera", normal="Vera", bold="Vera-Bold", italic="Vera-Italic", boldItalic="Vera-Bold"
    )
    CMAP.update(pdfmetrics.getFont("Vera").face.charToGlyph.keys())
    _REGISTERED = True


class Sanitizer:
    """Replace characters the font cannot render with a visible marker; count and remember them."""

    def __init__(self) -> None:
        register_fonts()
        self.replaced = 0
        self.examples: list[str] = []

    def __call__(self, text) -> str:
        out = []
        for ch in str(text):
            cp = ord(ch)
            if ch in "\n\t" or cp in CMAP:
                out.append(ch)
            else:
                self.replaced += 1
                mark = f"[U+{cp:04X}]"
                if mark not in self.examples and len(self.examples) < 10:
                    self.examples.append(mark)
                out.append(mark)
        return "".join(out)


class Styles:
    def __init__(self, base: float = 8.5) -> None:
        register_fonts()
        self.body = ParagraphStyle("body", fontName="Vera", fontSize=base, leading=base * 1.35)
        self.small = ParagraphStyle("small", parent=self.body, fontSize=base - 1.5, leading=base)
        self.cell = ParagraphStyle(
            "cell", parent=self.body, fontSize=base - 2, leading=base - 0.5, wordWrap="CJK"
        )
        self.cell_b = ParagraphStyle("cell_b", parent=self.cell, fontName="Vera-Bold")
        self.h1 = ParagraphStyle(
            "h1", parent=self.body, fontName="Vera-Bold", fontSize=base + 5, leading=base + 8,
            spaceBefore=10, spaceAfter=5, keepWithNext=1,
        )  # fmt: skip
        self.h2 = ParagraphStyle(
            "h2", parent=self.body, fontName="Vera-Bold", fontSize=base + 2, leading=base + 5,
            spaceBefore=8, spaceAfter=3, keepWithNext=1,
        )  # fmt: skip
        self.title = ParagraphStyle(
            "title", parent=self.body, fontName="Vera-Bold", fontSize=22, leading=27, spaceAfter=6
        )
        self.note = ParagraphStyle(
            "note", parent=self.body, fontName="Vera-Italic", fontSize=base - 1, leading=base + 1
        )
        self.banner = ParagraphStyle(
            "banner", parent=self.body, fontName="Vera-Bold", fontSize=base + 3,
            leading=base + 6, alignment=1,
        )  # fmt: skip


def make_canvas(footer_left: str, banner: str | None, san: Sanitizer) -> type:
    left, ban = san(footer_left), san(banner) if banner else None

    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._saved: list[dict] = []

        def showPage(self):  # noqa: N802 (ReportLab API)
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            n = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self._decorate(n)
                super().showPage()
            super().save()

        def _decorate(self, total: int) -> None:
            w, h = A4
            self.setFont("Vera", 7)
            self.setFillColor(colors.HexColor("#444444"))
            self.drawString(14 * mm, 9 * mm, left)
            self.drawRightString(w - 14 * mm, 9 * mm, f"Page {self._pageNumber} of {total}")
            self.setStrokeColor(colors.HexColor("#999999"))
            self.line(14 * mm, 12 * mm, w - 14 * mm, 12 * mm)
            if ban:
                self.setFont("Vera-Bold", 7.5)
                self.setFillColor(colors.HexColor("#9b1c1c"))
                self.drawCentredString(w / 2, h - 8 * mm, ban)

    return NumberedCanvas


def build_pdf(
    story_fn: Callable[[Sanitizer, Styles], list],
    *,
    title: str,
    footer_left: str,
    banner: str | None = None,
) -> tuple[bytes, int, Sanitizer]:
    """Render `story_fn(sanitizer, styles)` to PDF bytes. Returns (bytes, page_count, sanitizer).
    The story function is called once, so sanitizer counts are final when it returns."""
    register_fonts()
    san = Sanitizer()
    st = Styles()
    base = make_canvas(footer_left, banner, san)  # sanitizes the footer before the story counts
    story = story_fn(san, st)
    buf = io.BytesIO()
    pages = {"n": 0}

    class Counting(base):  # type: ignore[misc, valid-type]
        def save(self):
            pages["n"] = len(self._saved)
            super().save()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=(18 if banner else 14) * mm,
        bottomMargin=16 * mm,
        title=san(title),
        author="Nirikshan",
        subject="Forensic DVR/NVR analysis report",
        creator="Nirikshan (ReportLab)",
        invariant=1,
    )
    doc.build(story, canvasmaker=Counting)
    return buf.getvalue(), pages["n"], san


def esc(san: Sanitizer, text) -> str:
    return escape(san("" if text is None else str(text)))


def para(san: Sanitizer, text, style, raw_markup: bool = False) -> Paragraph:
    """Paragraph from plain text (escaped, sanitized). `raw_markup` allows <b>/<br/> in text that
    the caller has already escaped."""
    body = text if raw_markup else esc(san, text).replace("\n", "<br/>")
    return Paragraph(body, style)


GRID = colors.HexColor("#b5b5b5")
HEAD_BG = colors.HexColor("#e6e9ee")


def table(
    san: Sanitizer,
    st: Styles,
    header: list[str],
    rows: list[list],
    widths: list[float],
    extra: list | None = None,
) -> Table:
    data = [[para(san, h, st.cell_b) for h in header]]
    for r in rows:
        data.append([c if not isinstance(c, (str, int, float, type(None))) else
                     para(san, "" if c is None else c, st.cell) for c in r])  # fmt: skip
    t = Table(data, colWidths=widths, repeatRows=1, splitByRow=1)
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, GRID),
                ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                *(extra or []),
            ]
        )
    )
    return t


def kv_table(san: Sanitizer, st: Styles, pairs: list[tuple[str, object]], w0: float = 42 * mm):
    rows = [[para(san, k, st.cell_b), para(san, v, st.cell)] for k, v in pairs]
    t = Table(rows, colWidths=[w0, 182 * mm - w0])
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, GRID),
                ("BACKGROUND", (0, 0), (0, -1), HEAD_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ]
        )
    )
    return t
