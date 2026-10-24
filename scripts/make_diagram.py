"""Render the README architecture diagram as a PNG.

GitHub's client-side mermaid enrichment does not run in every reader (mobile
apps, some clients, PDF exports), so the pipeline diagram ships as a static
image instead. Regenerate with:

    python make_diagram.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 2                      # supersample, then downscale for smooth edges
W, H = 2000, 1000
OUT = Path(__file__).resolve().parent.parent / "screenshots" / "architecture.png"

FONT = r"C:\Windows\Fonts\segoeui.ttf"
FONT_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"

INK, MUTED, LINE = "#1f2328", "#59636e", "#8c959f"
NEUTRAL_FILL, NEUTRAL_EDGE = "#f6f8fa", "#d0d7de"
BLUE = "#1f6feb"
GREEN_FILL, GREEN_EDGE, GREEN_INK = "#dafbe1", "#4ac26b", "#1a7f37"
AMBER_FILL, AMBER_EDGE, AMBER_INK = "#fff8c5", "#d4a72c", "#9a6700"
RED_FILL, RED_EDGE, RED_INK = "#ffebe9", "#ff8182", "#cf222e"

MIDDOT = "\u00b7"
DASH = "\u2014"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size * S)


def box(draw, x0, y0, x1, y1, fill, edge, width=3, radius=14):
    draw.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=radius * S,
                           fill=fill, outline=edge, width=int(width * S))


def centred(draw, cx, y, text, f, fill):
    w = draw.textlength(text, font=f)
    draw.text((cx * S - w / 2, y * S), text, font=f, fill=fill)


def head(draw, tip, u, color, length=13, width=10):
    """Fill a triangular arrowhead at `tip`, pointing along unit vector `u`."""
    bx, by = tip[0] - u[0] * length, tip[1] - u[1] * length
    px, py = -u[1], u[0]
    draw.polygon([
        (tip[0] * S, tip[1] * S),
        ((bx + px * width / 2) * S, (by + py * width / 2) * S),
        ((bx - px * width / 2) * S, (by - py * width / 2) * S),
    ], fill=color)


def arrow(draw, x0, y0, x1, y1, color=LINE, width=2.5, dashed=False):
    x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    u = (dx / length, dy / length)
    tip_len = 12
    shaft_end = (x1 - u[0] * tip_len, y1 - u[1] * tip_len)

    if dashed:
        pos, dash, step = 0.0, 9, 15
        while pos < length - tip_len:
            end = min(pos + dash, length - tip_len)
            draw.line([((x0 + u[0] * pos) * S, (y0 + u[1] * pos) * S),
                       ((x0 + u[0] * end) * S, (y0 + u[1] * end) * S)],
                      fill=color, width=int(width * S))
            pos += step
    else:
        draw.line([(x0 * S, y0 * S), (shaft_end[0] * S, shaft_end[1] * S)],
                  fill=color, width=int(width * S))
    head(draw, (x1, y1), u, color)


def main() -> None:
    img = Image.new("RGB", (W * S, H * S), "#ffffff")
    d = ImageDraw.Draw(img)

    d.text((60 * S, 40 * S), "TriageOps pipeline", font=font(34, True), fill=INK)
    d.text((60 * S, 88 * S),
           f"three stages {MIDDOT} a checkpoint at the end of each {MIDDOT} "
           "the decision is code, not the model",
           font=font(22), fill=MUTED)

    top, bottom = 200, 412
    mid = (top + bottom) / 2
    stages = [
        (60, 380, "Claim", "free-text customer claim", None, NEUTRAL_FILL),
        (470, 790, "1 " + MIDDOT + " intake", "classify + extract work order",
         "checkpoint: enum + work order", "#ffffff"),
        (880, 1200, "2 " + MIDDOT + " evidence", "bounded tool loop " + MIDDOT + " max 6 calls",
         "checkpoint: docs + record + Cpk", "#ffffff"),
        (1290, 1610, "3 " + MIDDOT + " decision", "computed by the rule engine",
         "checkpoint: cited ids valid", "#ffffff"),
    ]

    for i, (x0, x1, title, sub, checkpoint, fill) in enumerate(stages):
        box(d, x0, top, x1, bottom, fill, NEUTRAL_EDGE)
        if checkpoint:
            d.rectangle([x0 * S, (top + 14) * S, (x0 + 6) * S, (bottom - 14) * S], fill=BLUE)
        centred(d, (x0 + x1) / 2, top + 44, title, font(27, True), INK)
        centred(d, (x0 + x1) / 2, top + 96, sub, font(19), MUTED)
        if checkpoint:
            centred(d, (x0 + x1) / 2, top + 148, checkpoint, font(17), MUTED)
        if i:
            arrow(d, stages[i - 1][1] + 14, mid, x0 - 14, mid)

    # confident path: decision -> outcomes
    d.line([(1450 * S, bottom * S), (1450 * S, 470 * S)], fill=LINE, width=6)
    d.line([(1210 * S, 470 * S), (1580 * S, 470 * S)], fill=LINE, width=6)
    arrow(d, 1210, 470, 1210, 505, color=LINE)
    arrow(d, 1580, 470, 1580, 505, color=LINE)

    box(d, 1050, 509, 1370, 629, AMBER_FILL, AMBER_EDGE)
    centred(d, 1210, 537, "Human review", font(26, True), AMBER_INK)
    centred(d, 1210, 581, "below the threshold", font(19), AMBER_INK)

    box(d, 1420, 509, 1740, 629, GREEN_FILL, GREEN_EDGE)
    centred(d, 1580, 537, "Auto-disposition", font(26, True), GREEN_INK)
    centred(d, 1580, 581, "evidence complete", font(19), GREEN_INK)

    # failure path
    arrow(d, 630, bottom + 6, 630, 700, color=RED_INK, dashed=True)
    box(d, 460, 704, 1000, 848, RED_FILL, RED_EDGE)
    centred(d, 730, 730, "Escalate", font(26, True), RED_INK)
    centred(d, 730, 774, "any checkpoint fails twice", font(19), RED_INK)
    centred(d, 730, 806, "R-NO-ORDER " + MIDDOT + " R-NO-CODE " + MIDDOT + " R-NO-SPC",
            font(18), RED_INK)

    # legend
    d.line([(60 * S, 930 * S), (126 * S, 930 * S)], fill=LINE, width=5)
    head(d, (138, 930), (1, 0), LINE, length=11, width=9)
    d.text((150 * S, 917 * S), "forward path", font=font(19), fill=MUTED)

    d.line([(310 * S, 930 * S), (350 * S, 930 * S)], fill=RED_INK, width=5)
    d.line([(365 * S, 930 * S), (398 * S, 930 * S)], fill=RED_INK, width=5)
    head(d, (411, 930), (1, 0), RED_INK, length=11, width=9)
    d.text((424 * S, 917 * S), f"failure path {DASH} checkpoint not satisfied",
           font=font(19), fill=MUTED)

    d.text((60 * S, 962 * S), f"All data is synthetic {DASH} generated by scripts/seed_data.py.",
           font=font(17), fill=MUTED)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.resize((W, H), Image.LANCZOS).save(OUT, optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KiB, {W}x{H})")


if __name__ == "__main__":
    main()
