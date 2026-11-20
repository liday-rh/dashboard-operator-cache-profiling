#!/usr/bin/env python3
"""Render pre/post dashboard cache benchmark charts from recorded TSV data."""

from __future__ import annotations

import csv
import statistics
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_RUN = ROOT / "output" / "results" / "20261119T184750Z-cache-optimization"
OUTPUT = REFERENCE_RUN / "charts"
PRE_FILE = REFERENCE_RUN / "dashboard-cache-baseline-samples.tsv"
POST_FILE = REFERENCE_RUN / "dashboard-cache-post-optimization-samples.tsv"

WIDTH, HEIGHT = 1800, 1000
BACKGROUND = "#ffffff"
TEXT = "#111827"
MUTED = "#4b5563"
GRID = "#d1d5db"
PRE = "#c2410c"
POST = "#0369a1"
LIMIT = "#b91c1c"

FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


TITLE = font(42, bold=True)
SUBTITLE = font(24)
LABEL = font(22)
LABEL_BOLD = font(22, bold=True)
TICK = font(18)
NOTE = font(19)
VALUE = font(20, bold=True)


def load(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def elapsed_minutes(rows: list[dict[str, str]]) -> list[float]:
    start = datetime.fromisoformat(rows[0]["timestamp"].replace("Z", "+00:00"))
    return [
        (datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")) - start).total_seconds() / 60
        for row in rows
    ]


def working_set(rows: list[dict[str, str]]) -> list[float]:
    return [float(row["working_set"].removesuffix("Mi")) for row in rows]


def metric_mib(rows: list[dict[str, str]], field: str) -> list[float]:
    return [float(row[field]) / 1048576 for row in rows]


def centered(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, face: ImageFont.FreeTypeFont, fill: str) -> None:
    box = draw.textbbox((0, 0), text, font=face)
    draw.text((xy[0] - (box[2] - box[0]) / 2, xy[1]), text, font=face, fill=fill)


def line_chart(pre_rows: list[dict[str, str]], post_rows: list[dict[str, str]]) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((80, 55), "Container working set over the benchmark window", font=TITLE, fill=TEXT)
    draw.text((80, 112), "350 namespaces · 3,500 objects · identical 20-sample windows", font=SUBTITLE, fill=MUTED)

    left, top, right, bottom = 150, 190, 1710, 805
    y_max = 360
    x_max = 10.5

    def sx(value: float) -> float:
        return left + value / x_max * (right - left)

    def sy(value: float) -> float:
        return bottom - value / y_max * (bottom - top)

    for value in [0, 64, 128, 192, 256, 320]:
        y = sy(value)
        draw.line((left, y, right, y), fill=GRID, width=2)
        label = f"{value} MiB"
        box = draw.textbbox((0, 0), label, font=TICK)
        draw.text((left - 18 - (box[2] - box[0]), y - 10), label, font=TICK, fill=MUTED)

    for value in [0, 2, 4, 6, 8, 10]:
        x = sx(value)
        draw.line((x, bottom, x, bottom + 10), fill=TEXT, width=2)
        centered(draw, (x, bottom + 18), str(value), TICK, MUTED)

    draw.line((left, top, left, bottom), fill=TEXT, width=3)
    draw.line((left, bottom, right, bottom), fill=TEXT, width=3)
    centered(draw, ((left + right) / 2, bottom + 55), "Elapsed time (minutes)", LABEL, TEXT)

    limit_y = sy(256)
    dash = 18
    x = left
    while x < right:
        draw.line((x, limit_y, min(x + dash, right), limit_y), fill=LIMIT, width=4)
        x += dash * 2
    draw.text((right - 220, limit_y - 34), "256 MiB limit", font=LABEL_BOLD, fill=LIMIT)

    pre_x, post_x = elapsed_minutes(pre_rows), elapsed_minutes(post_rows)
    pre_y, post_y = working_set(pre_rows), working_set(post_rows)
    pre_points = [(sx(xv), sy(yv)) for xv, yv in zip(pre_x, pre_y)]
    post_points = [(sx(xv), sy(yv)) for xv, yv in zip(post_x, post_y)]
    draw.line(pre_points, fill=PRE, width=7, joint="curve")
    draw.line(post_points, fill=POST, width=7, joint="curve")

    for x, y in pre_points:
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=BACKGROUND, outline=PRE, width=4)
    for x, y in post_points:
        draw.rectangle((x - 6, y - 6, x + 6, y + 6), fill=BACKGROUND, outline=POST, width=4)

    legend_y = 150
    draw.line((1120, legend_y, 1180, legend_y), fill=PRE, width=7)
    draw.ellipse((1144, legend_y - 6, 1156, legend_y + 6), fill=BACKGROUND, outline=PRE, width=4)
    draw.text((1195, legend_y - 13), "Pre-optimization (1 GiB profiling limit)", font=NOTE, fill=TEXT)
    draw.line((1120, legend_y + 42, 1180, legend_y + 42), fill=POST, width=7)
    draw.rectangle((1144, legend_y + 36, 1156, legend_y + 48), fill=BACKGROUND, outline=POST, width=4)
    draw.text((1195, legend_y + 29), "Post-optimization (256 MiB limit)", font=NOTE, fill=TEXT)

    pre_median = statistics.median(pre_y)
    post_median = statistics.median(post_y)
    draw.text((80, 905), f"Median: {pre_median:.0f} MiB before → {post_median:.0f} MiB after (87.8% lower)", font=LABEL_BOLD, fill=TEXT)
    draw.text((80, 942), "The pre-optimization process OOM-killed after 18 seconds at 256 MiB; its steady-state samples required a temporary 1 GiB limit.", font=NOTE, fill=MUTED)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT / "cache-working-set-over-time.png", optimize=True)


def bar_chart(pre_rows: list[dict[str, str]], post_rows: list[dict[str, str]]) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((80, 55), "Median memory footprint", font=TITLE, fill=TEXT)
    draw.text((80, 112), "Pre-optimization versus complete cache-optimization series", font=SUBTITLE, fill=MUTED)

    categories = ["Working set", "Process RSS", "Heap allocated", "Heap in use"]
    pre_values = [
        statistics.median(working_set(pre_rows)),
        statistics.median(metric_mib(pre_rows, "process_rss_bytes")),
        statistics.median(metric_mib(pre_rows, "heap_alloc_bytes")),
        statistics.median(metric_mib(pre_rows, "heap_inuse_bytes")),
    ]
    post_values = [
        statistics.median(working_set(post_rows)),
        statistics.median(metric_mib(post_rows, "process_rss_bytes")),
        statistics.median(metric_mib(post_rows, "heap_alloc_bytes")),
        statistics.median(metric_mib(post_rows, "heap_inuse_bytes")),
    ]
    reductions = [(1 - post / pre) * 100 for pre, post in zip(pre_values, post_values)]

    left, top, right, bottom = 150, 200, 1710, 790
    y_max = 380

    def sy(value: float) -> float:
        return bottom - value / y_max * (bottom - top)

    for value in [0, 100, 200, 300]:
        y = sy(value)
        draw.line((left, y, right, y), fill=GRID, width=2)
        label = f"{value} MiB"
        box = draw.textbbox((0, 0), label, font=TICK)
        draw.text((left - 18 - (box[2] - box[0]), y - 10), label, font=TICK, fill=MUTED)
    draw.line((left, top, left, bottom), fill=TEXT, width=3)
    draw.line((left, bottom, right, bottom), fill=TEXT, width=3)

    centers = [340, 720, 1100, 1480]
    bar_width = 115
    gap = 28
    for center, category, pre, post, reduction in zip(centers, categories, pre_values, post_values, reductions):
        pre_left = center - gap / 2 - bar_width
        post_left = center + gap / 2
        pre_top = sy(pre)
        post_top = sy(post)
        draw.rectangle((pre_left, pre_top, pre_left + bar_width, bottom), fill=PRE)
        draw.rectangle((post_left, post_top, post_left + bar_width, bottom), fill=POST)
        centered(draw, (pre_left + bar_width / 2, pre_top - 34), f"{pre:.1f}", VALUE, PRE)
        centered(draw, (post_left + bar_width / 2, post_top - 34), f"{post:.1f}", VALUE, POST)
        centered(draw, (center, bottom + 24), category, LABEL, TEXT)
        centered(draw, (center, bottom + 62), f"↓ {reduction:.1f}%", LABEL_BOLD, POST)

    draw.rectangle((1210, 150, 1235, 175), fill=PRE)
    draw.text((1248, 149), "Pre-optimization", font=NOTE, fill=TEXT)
    draw.rectangle((1450, 150, 1475, 175), fill=POST)
    draw.text((1488, 149), "Post-optimization", font=NOTE, fill=TEXT)

    draw.text((80, 930), "All four median memory measures fell by at least 83%; allocated heap fell by 94.6%.", font=LABEL_BOLD, fill=TEXT)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT / "cache-memory-medians.png", optimize=True)


def main() -> None:
    pre_rows = load(PRE_FILE)
    post_rows = load(POST_FILE)
    if len(pre_rows) != 20 or len(post_rows) != 20:
        raise SystemExit("expected exactly 20 samples in each dataset")
    line_chart(pre_rows, post_rows)
    bar_chart(pre_rows, post_rows)
    print(OUTPUT / "cache-working-set-over-time.png")
    print(OUTPUT / "cache-memory-medians.png")


if __name__ == "__main__":
    main()
