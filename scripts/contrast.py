"""WCAG 2.1 contrast ratios for the text/background pairs used by the UI (Tailwind colours).

`python scripts/contrast.py` prints every pair and exits 1 if a pair used for normal text is
below 4.5:1 (large text / UI components need 3:1, listed separately). Keep PAIRS in sync with
frontend/src/index.css and the classes the pages use; docs/accessibility.md records the table.
"""

import sys

BG = {
    "navy-900": "#0a1628",
    "navy-800": "#0f2040",
    "navy-700": "#16305c",
    "accent": "#f97316",
    "accent-strong": "#c2410c",
    "emerald-900": "#064e3b",
    "amber-900": "#78350f",
    "red-900": "#7f1d1d",
    "slate-700": "#334155",
    "amber-400": "#fbbf24",
}
FG = {
    "white": "#ffffff",
    "slate-100": "#f1f5f9",
    "slate-300": "#cbd5e1",
    "slate-400": "#94a3b8",
    "slate-500": "#64748b",
    "accent": "#f97316",
    "emerald-400": "#34d399",
    "amber-300": "#fcd34d",
    "amber-400": "#fbbf24",
    "red-400": "#f87171",
    "red-500": "#ef4444",
    "emerald-200": "#a7f3d0",
    "amber-200": "#fde68a",
    "red-200": "#fecaca",
    "slate-300b": "#cbd5e1",
    "navy-900": "#0a1628",
}

# (foreground, background, min ratio, where used)
PAIRS = [
    ("slate-100", "navy-900", 4.5, "body text"),
    ("slate-100", "navy-800", 4.5, "card text"),
    ("slate-300", "navy-800", 4.5, "secondary text"),
    ("slate-400", "navy-800", 4.5, "hint text (was slate-500)"),
    ("slate-400", "navy-900", 4.5, "hint text on page"),
    ("slate-500", "navy-800", 4.5, "OLD hint text (fails)"),
    ("accent", "navy-900", 4.5, "links on page"),
    ("accent", "navy-800", 4.5, "links on cards"),
    ("white", "accent", 4.5, "OLD button/active nav text (fails)"),
    ("navy-900", "accent", 4.5, "NEW button/active nav text"),
    ("white", "accent-strong", 4.5, "alternative button text"),
    ("emerald-400", "navy-800", 4.5, "status ok"),
    ("amber-300", "navy-800", 4.5, "warnings"),
    ("amber-400", "navy-800", 4.5, "status partial"),
    ("red-400", "navy-800", 4.5, "errors"),
    ("red-400", "navy-900", 4.5, "errors on page"),
    ("red-500", "navy-800", 4.5, "OLD offline dot text"),
    ("emerald-200", "emerald-900", 4.5, "parsed chip"),
    ("amber-200", "amber-900", 4.5, "inferred chip"),
    ("slate-300", "slate-700", 4.5, "unknown chip"),
    ("navy-900", "amber-400", 4.5, "SYNTHETIC / timezone banners"),
    ("red-200", "red-900", 4.5, "error banner"),
    ("accent", "navy-800", 3.0, "focus ring / UI component (3:1)"),
]


def lum(h: str) -> float:
    h = h.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def f(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def main() -> int:
    bad = 0
    for fg, bg, need, where in PAIRS:
        r = ratio(FG[fg], BG[bg])
        ok = r >= need
        old = where.startswith("OLD")
        bad += (not ok) and not old
        print(f"{'PASS' if ok else 'FAIL'}  {r:5.2f}:1 (>= {need})  {fg:12} on {bg:14} {where}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
