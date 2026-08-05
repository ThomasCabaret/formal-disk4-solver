from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from reportlab.lib.colors import Color, HexColor, white
    from reportlab.lib.units import inch
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen.canvas import Canvas
except ImportError as error:  # pragma: no cover - documentation dependency
    raise SystemExit(
        "ReportLab is required. Install it with: py.exe -m pip install reportlab"
    ) from error


PAGE_SIZE = (13.333 * inch, 7.5 * inch)
MARGIN = 34.0
HEADER = 55.0
FOOTER = 25.0

PALETTE = {
    "background": HexColor("#F4F7FB"),
    "ink": HexColor("#172033"),
    "muted": HexColor("#5E6B82"),
    "line": HexColor("#B9C4D5"),
    "data": HexColor("#64748B"),
    "integrity": HexColor("#667085"),
    "enumeration": HexColor("#0F766E"),
    "ordering": HexColor("#0F766E"),
    "quotient": HexColor("#2563EB"),
    "domain": HexColor("#7C3AED"),
    "theorem": HexColor("#15803D"),
    "necessary": HexColor("#15803D"),
    "exact": HexColor("#047857"),
    "resource": HexColor("#B7791F"),
    "numerical": HexColor("#C2410C"),
    "output": HexColor("#0369A1"),
}


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("diagram source must contain one JSON object")
    return payload


def _shade(color: Color, factor: float = 0.90) -> Color:
    return Color(
        color.red + (1.0 - color.red) * factor,
        color.green + (1.0 - color.green) * factor,
        color.blue + (1.0 - color.blue) * factor,
    )


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words = str(text).split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        proposal = f"{current} {word}"
        if stringWidth(proposal, font, size) <= width:
            current = proposal
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _text(
    canvas: Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "Helvetica",
    size: float = 8.0,
    color: Color | None = None,
    leading: float | None = None,
    max_lines: int | None = None,
) -> float:
    lines = _wrap(text, font, size, width)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        final = lines[-1]
        while final and stringWidth(final + "...", font, size) > width:
            final = final[:-1]
        lines[-1] = final.rstrip() + "..."
    leading = leading or size * 1.22
    canvas.setFont(font, size)
    canvas.setFillColor(color or PALETTE["ink"])
    cursor = y
    for line in lines:
        canvas.drawString(x, cursor, line)
        cursor -= leading
    return cursor


def _header(canvas: Canvas, source: Mapping[str, Any], page: Mapping[str, Any], number: int, total: int) -> None:
    width, height = PAGE_SIZE
    canvas.setFillColor(PALETTE["background"])
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(PALETTE["ink"])
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(MARGIN, height - 28, str(page["title"]))
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(PALETTE["muted"])
    canvas.drawString(MARGIN, height - 43, str(page.get("subtitle", "")))
    canvas.setStrokeColor(PALETTE["line"])
    canvas.line(MARGIN, height - HEADER, width - MARGIN, height - HEADER)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(PALETTE["muted"])
    canvas.drawString(MARGIN, 12, f"{source['title']}  |  revision {source['revision']}")
    label = f"{number}/{total}"
    canvas.drawRightString(width - MARGIN, 12, label)


def _arrow(canvas: Canvas, x1: float, y1: float, x2: float, y2: float, color: Color | None = None) -> None:
    color = color or PALETTE["line"]
    canvas.setStrokeColor(color)
    canvas.setFillColor(color)
    canvas.setLineWidth(1.2)
    if abs(x2 - x1) > 4 and abs(y2 - y1) > 4:
        mid = (x1 + x2) / 2
        canvas.line(x1, y1, mid, y1)
        canvas.line(mid, y1, mid, y2)
        canvas.line(mid, y2, x2, y2)
    else:
        canvas.line(x1, y1, x2, y2)
    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    if abs(x2 - x1) > 4 and abs(y2 - y1) > 4:
        angle = 0.0
    length = 5.0
    spread = 2.5
    tip = (x2, y2)
    back = (x2 - length * math.cos(angle), y2 - length * math.sin(angle))
    normal = (-math.sin(angle), math.cos(angle))
    path = canvas.beginPath()
    path.moveTo(*tip)
    path.lineTo(back[0] + spread * normal[0], back[1] + spread * normal[1])
    path.lineTo(back[0] - spread * normal[0], back[1] - spread * normal[1])
    path.close()
    canvas.drawPath(path, fill=1, stroke=0)


def _badge(canvas: Canvas, kind: str, x: float, y: float, width: float = 52.0) -> None:
    color = PALETTE.get(kind, PALETTE["data"])
    canvas.setFillColor(color)
    canvas.roundRect(x, y, width, 11, 5, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Helvetica-Bold", 5.8)
    canvas.drawCentredString(x + width / 2, y + 3.1, kind.upper())


def _card(canvas: Canvas, card: Mapping[str, Any], x: float, y: float, width: float, height: float) -> None:
    kind = str(card.get("kind", "data"))
    color = PALETTE.get(kind, PALETTE["data"])
    canvas.setFillColor(white)
    canvas.setStrokeColor(color)
    canvas.setLineWidth(1.3)
    canvas.roundRect(x, y, width, height, 6, fill=1, stroke=1)
    canvas.setFillColor(color)
    canvas.roundRect(x, y + height - 7, width, 7, 6, fill=1, stroke=0)
    canvas.rect(x, y + height - 7, width, 3, fill=1, stroke=0)
    canvas.setFillColor(PALETTE["muted"])
    canvas.setFont("Helvetica-Bold", 6.0)
    canvas.drawString(x + 8, y + height - 17, str(card.get("id", "")))
    _badge(canvas, kind, x + width - 59, y + height - 21)
    title_y = y + height - 31
    title_lines = _wrap(str(card["title"]), "Helvetica-Bold", 8.2, width - 16)
    canvas.setFont("Helvetica-Bold", 8.2)
    canvas.setFillColor(PALETTE["ink"])
    for line in title_lines[:2]:
        canvas.drawString(x + 8, title_y, line)
        title_y -= 9.5
    body_bottom = y + (18 if card.get("exit") else 7)
    available = max(1, int((title_y - body_bottom) / 7.7))
    _text(
        canvas,
        str(card.get("body", "")),
        x + 8,
        title_y - 2,
        width - 16,
        size=6.5,
        leading=7.7,
        color=PALETTE["muted"],
        max_lines=available,
    )
    if card.get("exit"):
        canvas.setFillColor(_shade(color, 0.86))
        canvas.roundRect(x + 6, y + 5, width - 12, 12, 3, fill=1, stroke=0)
        _text(
            canvas,
            "EXIT: " + str(card["exit"]),
            x + 10,
            y + 8.2,
            width - 20,
            font="Helvetica-Bold",
            size=5.4,
            leading=6.0,
            color=color,
            max_lines=1,
        )


def _legend(canvas: Canvas, y: float) -> None:
    entries = [
        ("quotient", "equivalence quotient"),
        ("domain", "imposed domain"),
        ("necessary", "necessary condition"),
        ("resource", "deferred / bounded"),
        ("numerical", "numerical non-proof"),
        ("output", "surviving output"),
    ]
    x = MARGIN
    for kind, label in entries:
        color = PALETTE[kind]
        canvas.setFillColor(color)
        canvas.circle(x + 4, y + 3, 3.5, fill=1, stroke=0)
        canvas.setFillColor(PALETTE["muted"])
        canvas.setFont("Helvetica", 6.2)
        canvas.drawString(x + 11, y, label)
        x += stringWidth(label, "Helvetica", 6.2) + 31


def _overview(canvas: Canvas, page: Mapping[str, Any]) -> None:
    width, height = PAGE_SIZE
    groups = list(page["groups"])
    gap = 10.0
    usable = width - 2 * MARGIN
    card_width = (usable - gap * (len(groups) - 1)) / len(groups)
    card_y = 180.0
    card_h = height - HEADER - FOOTER - card_y + 10
    centers = []
    for index, group in enumerate(groups):
        x = MARGIN + index * (card_width + gap)
        kind = str(group["kind"])
        color = PALETTE[kind]
        canvas.setFillColor(white)
        canvas.setStrokeColor(color)
        canvas.setLineWidth(1.5)
        canvas.roundRect(x, card_y, card_width, card_h, 8, fill=1, stroke=1)
        canvas.setFillColor(color)
        canvas.roundRect(x, card_y + card_h - 35, card_width, 35, 8, fill=1, stroke=0)
        canvas.rect(x, card_y + card_h - 35, card_width, 8, fill=1, stroke=0)
        canvas.setFillColor(white)
        canvas.setFont("Helvetica-Bold", 8.2)
        canvas.drawCentredString(x + card_width / 2, card_y + card_h - 22, str(group["name"]))
        cursor = _text(
            canvas,
            str(group["summary"]),
            x + 9,
            card_y + card_h - 50,
            card_width - 18,
            font="Helvetica-Bold",
            size=7.2,
            leading=9,
            max_lines=5,
        )
        cursor -= 5
        for item in group.get("items", []):
            canvas.setFillColor(color)
            canvas.circle(x + 12, cursor + 2.5, 2.1, fill=1, stroke=0)
            cursor = _text(
                canvas,
                str(item),
                x + 19,
                cursor,
                card_width - 28,
                size=6.7,
                leading=8.2,
                color=PALETTE["muted"],
                max_lines=2,
            ) - 2
        centers.append((x, card_y, card_width, card_h))
    for left, right in zip(centers, centers[1:]):
        _arrow(
            canvas,
            left[0] + left[2],
            left[1] + left[3] / 2,
            right[0],
            right[1] + right[3] / 2,
        )

    sidecar = page["sidecar"]
    sx, sy, sw, sh = MARGIN, 73.0, usable, 73.0
    color = PALETTE["domain"]
    canvas.setFillColor(_shade(color, 0.91))
    canvas.setStrokeColor(color)
    canvas.setDash(4, 3)
    canvas.roundRect(sx, sy, sw, sh, 8, fill=1, stroke=1)
    canvas.setDash()
    canvas.setFillColor(color)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(sx + 13, sy + sh - 20, str(sidecar["title"]))
    _text(canvas, str(sidecar["text"]), sx + 13, sy + sh - 37, sw - 26, size=7.7, leading=9.5, max_lines=3)
    _legend(canvas, 42)


def _lanes(canvas: Canvas, page: Mapping[str, Any]) -> None:
    width, height = PAGE_SIZE
    lanes = list(page["lanes"])
    gap = 13.0
    usable_w = width - 2 * MARGIN
    lane_w = (usable_w - gap * (len(lanes) - 1)) / len(lanes)
    top = height - HEADER - 27
    bottom = 70.0
    lane_header_h = 20.0
    max_cards = max(len(lane["cards"]) for lane in lanes)
    card_gap = 6.0
    card_h = (top - bottom - lane_header_h - (max_cards - 1) * card_gap) / max_cards
    positions: dict[str, tuple[float, float, float, float]] = {}
    previous: tuple[float, float, float, float] | None = None

    for lane_index, lane in enumerate(lanes):
        x = MARGIN + lane_index * (lane_w + gap)
        canvas.setFillColor(HexColor("#E8EDF5"))
        canvas.roundRect(x, bottom - 5, lane_w, top - bottom + 10, 8, fill=1, stroke=0)
        canvas.setFillColor(PALETTE["ink"])
        canvas.setFont("Helvetica-Bold", 7.2)
        canvas.drawCentredString(x + lane_w / 2, top - 14, str(lane["name"]))
        for card_index, card in enumerate(lane["cards"]):
            y = top - lane_header_h - (card_index + 1) * card_h - card_index * card_gap
            _card(canvas, card, x + 5, y, lane_w - 10, card_h)
            current = (x + 5, y, lane_w - 10, card_h)
            positions[str(card["id"])] = current
            if previous is not None:
                px, py, pw, ph = previous
                cx, cy, cw, ch = current
                if abs(cx - px) < 2:
                    _arrow(canvas, px + pw / 2, py - 1, cx + cw / 2, cy + ch + 1)
                else:
                    _arrow(canvas, px + pw, py + ph / 2, cx, cy + ch / 2)
            previous = current

    canvas.setFillColor(PALETTE["muted"])
    canvas.setFont("Helvetica-Oblique", 6.4)
    _text(canvas, str(page.get("note", "")), MARGIN, 52, usable_w, font="Helvetica-Oblique", size=6.4, leading=7.5, max_lines=2)
    _legend(canvas, 31)


def _audit(canvas: Canvas, page: Mapping[str, Any]) -> None:
    width, height = PAGE_SIZE
    categories = list(page["categories"])
    gap = 8.0
    usable = width - 2 * MARGIN
    category_w = (usable - gap * (len(categories) - 1)) / len(categories)
    category_y = height - HEADER - 103
    for index, category in enumerate(categories):
        x = MARGIN + index * (category_w + gap)
        color = PALETTE[str(category["kind"])]
        canvas.setFillColor(white)
        canvas.setStrokeColor(color)
        canvas.roundRect(x, category_y, category_w, 77, 6, fill=1, stroke=1)
        canvas.setFillColor(color)
        canvas.rect(x, category_y + 70, category_w, 7, fill=1, stroke=0)
        _text(canvas, str(category["title"]), x + 7, category_y + 58, category_w - 14, font="Helvetica-Bold", size=6.8, color=color, max_lines=2)
        _text(canvas, str(category["text"]), x + 7, category_y + 36, category_w - 14, size=5.8, leading=6.8, color=PALETTE["muted"], max_lines=5)

    questions = list(page["questions"])
    table_top = category_y - 18
    row_gap = 7.0
    row_h = 67.0
    for index, question in enumerate(questions):
        y = table_top - (index + 1) * row_h - index * row_gap
        color = PALETTE["theorem"] if index < 2 else PALETTE["exact"]
        canvas.setFillColor(white)
        canvas.setStrokeColor(PALETTE["line"])
        canvas.roundRect(MARGIN, y, usable, row_h, 6, fill=1, stroke=1)
        canvas.setFillColor(color)
        canvas.roundRect(MARGIN, y, 39, row_h, 6, fill=1, stroke=0)
        canvas.rect(MARGIN + 33, y, 6, row_h, fill=1, stroke=0)
        canvas.setFillColor(white)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawCentredString(MARGIN + 19.5, y + row_h / 2 - 4, str(question["id"]))
        title_x = MARGIN + 49
        canvas.setFillColor(PALETTE["ink"])
        canvas.setFont("Helvetica-Bold", 8.2)
        canvas.drawString(title_x, y + row_h - 15, str(question["title"]))
        split = title_x + usable * 0.58
        _text(canvas, str(question["math"]), title_x, y + row_h - 29, split - title_x - 14, size=6.3, leading=7.5, max_lines=5)
        canvas.setFillColor(_shade(color, 0.91))
        canvas.roundRect(split, y + 7, MARGIN + usable - split - 7, row_h - 14, 4, fill=1, stroke=0)
        _text(canvas, "NEEDED: " + str(question["needed"]), split + 8, y + row_h - 21, MARGIN + usable - split - 23, font="Helvetica-Bold", size=6.0, leading=7.1, color=color, max_lines=5)

    canvas.setFillColor(HexColor("#FFF4E5"))
    canvas.setStrokeColor(PALETTE["numerical"])
    canvas.roundRect(MARGIN, 29, usable, 31, 5, fill=1, stroke=1)
    _text(canvas, "WARNING: " + str(page["warning"]), MARGIN + 9, 48, usable - 18, font="Helvetica-Bold", size=6.2, leading=7.4, color=PALETTE["numerical"], max_lines=2)


def _code_map(canvas: Canvas, page: Mapping[str, Any]) -> None:
    width, height = PAGE_SIZE
    rows = list(page["rows"])
    x = MARGIN
    top = height - HEADER - 18
    usable = width - 2 * MARGIN
    columns = (usable * 0.22, usable * 0.49, usable * 0.29)
    headers = ("Pipeline responsibility", "Primary module(s)", "Key entry point(s)")
    row_h = (top - 34) / (len(rows) + 1)
    cursor = top
    canvas.setFillColor(PALETTE["ink"])
    canvas.rect(x, cursor - row_h, usable, row_h, fill=1, stroke=0)
    offset = x
    for header, column in zip(headers, columns):
        canvas.setFillColor(white)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawString(offset + 7, cursor - row_h + row_h / 2 - 2.5, header)
        offset += column
    cursor -= row_h
    for index, row in enumerate(rows):
        canvas.setFillColor(white if index % 2 == 0 else HexColor("#EAF0F7"))
        canvas.rect(x, cursor - row_h, usable, row_h, fill=1, stroke=0)
        canvas.setStrokeColor(PALETTE["line"])
        canvas.line(x, cursor - row_h, x + usable, cursor - row_h)
        offset = x
        for column_index, (value, column) in enumerate(zip(row, columns)):
            _text(
                canvas,
                str(value),
                offset + 7,
                cursor - row_h + row_h / 2 + 2,
                column - 14,
                font="Helvetica-Bold" if column_index == 0 else "Helvetica",
                size=6.1,
                leading=6.8,
                max_lines=2,
            )
            offset += column
        cursor -= row_h


def render(source_path: Path, output_path: Path) -> None:
    source = _load(source_path)
    pages = list(source["pages"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    canvas = Canvas(str(temporary), pagesize=PAGE_SIZE, pageCompression=1)
    canvas.setTitle(str(source["title"]))
    canvas.setAuthor("formal_disk4 solver documentation")
    for index, page in enumerate(pages, start=1):
        _header(canvas, source, page, index, len(pages))
        layout = str(page["layout"])
        if layout == "overview":
            _overview(canvas, page)
        elif layout == "lanes":
            _lanes(canvas, page)
        elif layout == "audit":
            _audit(canvas, page)
        elif layout == "code_map":
            _code_map(canvas, page)
        else:
            raise ValueError(f"unknown page layout {layout!r}")
        canvas.showPage()
    canvas.save()
    temporary.replace(output_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the editable solver pipeline diagram")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("docs/solver_pipeline_diagram.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/pdf/formal_disk4_solver_pipeline.pdf"),
    )
    args = parser.parse_args(argv)
    render(args.source.resolve(), args.output.resolve())
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
