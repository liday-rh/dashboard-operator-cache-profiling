#!/usr/bin/env python3
"""Render a reusable run directory into the canonical Markdown report."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any


PRE = "#d55e00"
POST = "#0072b2"
GRID = "#dfe3e8"
TEXT = "#202124"
MUTED = "#5f6368"
TYPE_PATHS = (
    "ConfigMap).Unmarshal",
    "Secret).Unmarshal",
    "Deployment).Unmarshal",
    "Service).Unmarshal",
    "ServiceAccount).Unmarshal",
    "RoleBinding).Unmarshal",
    "ClusterRole).Unmarshal",
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text())


def load_samples(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open() as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def mib(value: str) -> float:
    return float(value.removesuffix("Mi"))


def number(value: str) -> float:
    return float(value)


def median(rows: list[dict[str, str]], field: str, convert=number) -> float | None:
    if not rows:
        return None
    return statistics.median(convert(row[field]) for row in rows)


def stats(rows: list[dict[str, str]]) -> dict[str, float | None]:
    if not rows:
        return {key: None for key in (
            "working_set", "working_set_max", "rss", "heap_alloc", "heap_inuse",
            "heap_objects", "cpu_delta", "reconcile_delta", "restarts_max"
        )}
    return {
        "working_set": median(rows, "working_set", mib),
        "working_set_max": max(mib(row["working_set"]) for row in rows),
        "rss": median(rows, "process_rss_bytes") / 1048576,
        "heap_alloc": median(rows, "heap_alloc_bytes") / 1048576,
        "heap_inuse": median(rows, "heap_inuse_bytes") / 1048576,
        "heap_objects": median(rows, "heap_objects"),
        "cpu_delta": number(rows[-1]["cpu_seconds"]) - number(rows[0]["cpu_seconds"]),
        "reconcile_delta": number(rows[-1]["dashboard_reconciles"]) - number(rows[0]["dashboard_reconciles"]),
        "restarts_max": max(number(row["restarts"]) for row in rows),
    }


def unit_bytes(value: str) -> float:
    match = re.fullmatch(r"([0-9.]+)(B|kB|MB|GB)", value)
    if not match:
        return 0.0
    amount = float(match.group(1))
    scale = {"B": 1, "kB": 1024, "MB": 1024**2, "GB": 1024**3}[match.group(2)]
    return amount * scale


def profile(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"total_display": "Not recorded", "total_mib": None, "paths": {}}
    text = path.read_text(errors="replace")
    total_match = re.search(r"of ([0-9.]+(?:kB|MB|GB|B)) total", text)
    total = total_match.group(1) if total_match else None
    paths: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6 or not parts[1].endswith("%") or not parts[4].endswith("%"):
            continue
        function = " ".join(parts[5:])
        for target in TYPE_PATHS:
            if target in function and target not in paths:
                paths[target] = {"flat": parts[0], "cum": parts[3]}
    return {
        "total_display": total or "Not recorded",
        "total_mib": unit_bytes(total) / 1048576 if total else None,
        "paths": paths,
    }


def object_total(path: Path) -> int | None:
    if not path.is_file():
        return None
    match = re.search(r"of ([0-9]+) total", path.read_text(errors="replace"))
    return int(match.group(1)) if match else None


def reduction(pre: float | None, post: float | None) -> float | None:
    if pre in (None, 0) or post is None:
        return None
    return (1 - post / pre) * 100


def fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "Not recorded"
    if isinstance(value, int) or float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.{digits}f}"


def fmt_count(value: float | int | None) -> str:
    if value is None:
        return "Not recorded"
    return f"{math.floor(float(value) + 0.5):,}"


def pct(value: float | None) -> str:
    return "Not recorded" if value is None else f"**{value:.1f}%**"


def ceil_scale(value: float, step: int = 100) -> int:
    return max(step, int(math.ceil(value / step) * step))


def svg_text(x: float, y: float, value: str, **attrs: str) -> str:
    attributes = " ".join(f'{key.replace("_", "-")}="{html.escape(str(val))}"' for key, val in attrs.items())
    return f'<text x="{x:.1f}" y="{y:.1f}" {attributes}>{html.escape(value)}</text>'


def summary_chart(results: list[dict[str, Any]], output: Path, limit_mib: float) -> None:
    width, height = 1400, 720
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#202124}.title{font-size:30px;font-weight:600}.sub{font-size:17px;fill:#5f6368}.label{font-size:16px}.value{font-size:16px;font-weight:600}.grid{stroke:#dfe3e8;stroke-width:1}.axis{stroke:#9aa0a6;stroke-width:2}.limit{stroke:#5f6368;stroke-width:2;stroke-dasharray:8 7}</style>',
        svg_text(60, 45, "Memory footprint comparison", **{"class": "title"}),
    ]
    panels = [
        ("Median working set", "MiB", "working_set", 60.0),
        ("Forced-GC retained heap", "MiB", "retained", 740.0),
    ]
    for title, unit, key, left in panels:
        right, top, bottom = left + 600, 150, 520
        values: list[float] = []
        for item in results:
            for variant in ("pre", "post"):
                value = item[variant]["stats"].get(key) if key != "retained" else item[variant]["profile"].get("total_mib")
                if value is not None:
                    values.append(float(value))
        y_max = ceil_scale(max(values + ([limit_mib] if key == "working_set" else [1])))
        lines.extend([
            svg_text(left, 92, title, **{"class": "title"}),
            svg_text(left, 120, unit + " · lower is better", **{"class": "sub"}),
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" class="axis"/>',
        ])
        for tick in range(0, y_max + 1, max(1, y_max // 4)):
            y = bottom - (tick / y_max) * (bottom - top)
            lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" class="grid"/>')
            lines.append(svg_text(left - 10, y + 5, str(tick), **{"text_anchor": "end", "class": "sub"}))
        if key == "working_set" and limit_mib <= y_max:
            y = bottom - (limit_mib / y_max) * (bottom - top)
            lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" class="limit"/>')
            lines.append(svg_text(right - 8, y - 8, f"{limit_mib:g} MiB limit", **{"text_anchor": "end", "class": "sub"}))
        group_width = (right - left) / max(1, len(results))
        for index, item in enumerate(results):
            center = left + group_width * (index + 0.5)
            for variant, offset, color in (("pre", -32, PRE), ("post", 32, POST)):
                value = item[variant]["stats"].get(key) if key != "retained" else item[variant]["profile"].get("total_mib")
                numeric = float(value or 0)
                bar_height = (numeric / y_max) * (bottom - top)
                x = center + offset - 27
                y = bottom - bar_height
                lines.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="54" height="{bar_height:.1f}" rx="3" fill="{color}"/>')
                if value is not None:
                    lines.append(svg_text(x + 27, max(top + 15, y - 8), fmt(numeric), **{"text_anchor": "middle", "class": "value"}))
            lines.append(svg_text(center, 555, item["label"], **{"text_anchor": "middle", "class": "label"}))
            pre_value = item["pre"]["stats"].get(key) if key != "retained" else item["pre"]["profile"].get("total_mib")
            post_value = item["post"]["stats"].get(key) if key != "retained" else item["post"]["profile"].get("total_mib")
            delta = reduction(pre_value, post_value)
            if delta is not None:
                lines.append(svg_text(center, 582, f"{delta:.1f}% lower", **{"text_anchor": "middle", "class": "value", "fill": POST}))
    lines.extend([
        f'<rect x="1030" y="25" width="18" height="18" fill="{PRE}"/><text x="1058" y="40" class="sub">Pre</text>',
        f'<rect x="1130" y="25" width="18" height="18" fill="{POST}"/><text x="1158" y="40" class="sub">Post</text>',
        "</svg>",
    ])
    output.write_text("\n".join(lines) + "\n")


def series_chart(results: list[dict[str, Any]], output: Path, limit_mib: float) -> None:
    width, height = 1400, 700
    left, right, top, bottom = 100, 1270, 100, 560
    all_values = [mib(row["working_set"]) for item in results for variant in ("pre", "post") for row in item[variant]["rows"]]
    y_max = ceil_scale(max(all_values + [limit_mib]))
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#202124}.title{font-size:30px;font-weight:600}.sub{font-size:16px;fill:#5f6368}.grid{stroke:#dfe3e8;stroke-width:1}.axis{stroke:#9aa0a6;stroke-width:2}.limit{stroke:#5f6368;stroke-width:2;stroke-dasharray:8 7}</style>',
        svg_text(60, 48, "Working set over time", **{"class": "title"}),
        svg_text(60, 76, "MiB · sample index", **{"class": "sub"}),
    ]
    for tick in range(0, y_max + 1, max(1, y_max // 7)):
        y = bottom - (tick / y_max) * (bottom - top)
        lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" class="grid"/>')
        lines.append(svg_text(left - 12, y + 5, str(tick), **{"text_anchor": "end", "class": "sub"}))
    limit_y = bottom - (limit_mib / y_max) * (bottom - top)
    lines.append(f'<line x1="{left}" y1="{limit_y:.1f}" x2="{right}" y2="{limit_y:.1f}" class="limit"/>')
    lines.append(svg_text(right - 8, limit_y - 8, f"{limit_mib:g} MiB limit", **{"text_anchor": "end", "class": "sub"}))
    legend_x = 100
    for scenario_index, item in enumerate(results):
        dash = "" if scenario_index == 0 else ' stroke-dasharray="10 7"'
        for variant, color in (("pre", PRE), ("post", POST)):
            rows = item[variant]["rows"]
            if not rows:
                continue
            points = []
            for index, row in enumerate(rows):
                x = left + (index / max(1, len(rows) - 1)) * (right - left)
                y = bottom - (mib(row["working_set"]) / y_max) * (bottom - top)
                points.append(f"{x:.1f},{y:.1f}")
            lines.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"{dash}/>' )
            lines.append(f'<line x1="{legend_x}" y1="635" x2="{legend_x + 45}" y2="635" stroke="{color}" stroke-width="4"{dash}/>')
            lines.append(svg_text(legend_x + 55, 641, f"{variant.title()} · {item['label']}", **{"class": "sub"}))
            legend_x += 250
    lines.append("</svg>")
    output.write_text("\n".join(lines) + "\n")


def observation(path: Path) -> dict[str, Any]:
    return load_json(path, {}) or {}


def build_results(run_dir: Path, config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    missing: list[str] = []
    for scenario in config["scenarios"]:
        scenario_dir = run_dir / "scenarios" / scenario["name"]
        variants: dict[str, Any] = {}
        for variant in ("pre", "post"):
            target = scenario_dir / variant
            rows = load_samples(target / "samples.tsv")
            if not rows:
                missing.append(f"{scenario['name']}/{variant}/samples.tsv")
            profile_data = profile(target / "heap-inuse-space.txt")
            if config["benchmark"].get("collect_pprof") and profile_data["total_mib"] is None:
                missing.append(f"{scenario['name']}/{variant}/heap-inuse-space.txt")
            variants[variant] = {
                "rows": rows,
                "stats": stats(rows),
                "profile": profile_data,
                "profile_objects": object_total(target / "heap-inuse-objects.txt"),
                "observation": observation(target / "observation.json"),
            }
        inventory = load_json(scenario_dir / "inventory.json", {}) or {}
        results.append({**scenario, "inventory": inventory, **variants})
    return results, missing


def fixture_text(item: dict[str, Any]) -> str:
    counts = item.get("inventory", {}).get("counts", {})
    objects = sum(int(value) for value in counts.values()) if counts else None
    base = f"{item['namespaces']} namespaces"
    if objects is not None:
        base += f", {objects:,} labelled objects"
    measured_bytes = item.get("inventory", {}).get("configmap_data_bytes")
    payload = (
        float(measured_bytes) / 1048576
        if measured_bytes is not None
        else item["namespaces"]
        * item["configmaps_per_namespace"]
        * item["configmap_payload_kib"]
        / 1024
    )
    if payload:
        base += f", approximately {payload:.2f} MiB ConfigMap data"
    return base + "."


def result_at_limit(item: dict[str, Any]) -> str:
    pre = item["pre"]["observation"]
    post = item["post"]["observation"]
    pre_result = pre.get("production_limit_result", "Not recorded")
    if pre.get("oom_seconds") is not None:
        pre_result += f" in {pre['oom_seconds']} s"
    post_result = post.get("production_limit_result", "Not recorded")
    return f"Pre: {pre_result}; post: {post_result}"


def render(run_dir: Path, config: dict[str, Any], results: list[dict[str, Any]], missing: list[str]) -> Path:
    charts = run_dir / "charts"
    charts.mkdir(exist_ok=True)
    limit_text = config["operator"].get("production_memory_limit", "256Mi")
    limit_mib = float(str(limit_text).removesuffix("Mi"))
    summary_chart(results, charts / "cache-summary-comparison.svg", limit_mib)
    series_chart(results, charts / "cache-working-set-series.svg", limit_mib)
    lines = [
        "# Dashboard cache optimization results",
        "",
        f"Run: `{config['run_id']}`  ",
        f"Created: {config['created_at']}",
        "",
        "## Summary",
        "",
        f"Pre/post comparison at the {limit_text} production memory limit.",
        "",
        "| Workload | Pre working set | Post working set | Reduction | Result at limit |",
        "|---|---:|---:|---:|---|",
    ]
    for item in results:
        pre = item["pre"]["stats"]["working_set"]
        post = item["post"]["stats"]["working_set"]
        lines.append(
            f"| {item['label']} | {fmt(pre)} MiB | {fmt(post)} MiB | {pct(reduction(pre, post))} | {result_at_limit(item)} |"
        )
    lines.extend([
        "",
        "![Working set and retained heap comparison](charts/cache-summary-comparison.svg)",
        "",
        "![Working set over time](charts/cache-working-set-series.svg)",
    ])
    metrics = (
        ("Container working set", "working_set", "MiB"),
        ("Process RSS", "rss", "MiB"),
        ("Go heap allocated", "heap_alloc", "MiB"),
        ("Go heap in use", "heap_inuse", "MiB"),
        ("Go heap objects", "heap_objects", ""),
    )
    for item in results:
        lines.extend(["", f"## {item['label']} workload", "", f"Fixture: {fixture_text(item)}", "", "| Median metric | Pre | Post | Reduction |", "|---|---:|---:|---:|"])
        for label, key, unit in metrics:
            pre = item["pre"]["stats"][key]
            post = item["post"]["stats"][key]
            suffix = f" {unit}" if unit else ""
            format_value = fmt_count if key == "heap_objects" else fmt
            lines.append(f"| {label} | {format_value(pre)}{suffix} | {format_value(post)}{suffix} | {pct(reduction(pre, post))} |")
        pre_heap = item["pre"]["profile"]["total_mib"]
        post_heap = item["post"]["profile"]["total_mib"]
        pre_objects = item["pre"]["profile_objects"]
        post_objects = item["post"]["profile_objects"]
        lines.append(f"| Forced-GC retained heap | {fmt(pre_heap)} MiB | {fmt(post_heap)} MiB | {pct(reduction(pre_heap, post_heap))} |")
        lines.append(f"| Forced-GC retained objects | {fmt_count(pre_objects)} | {fmt_count(post_objects)} | {pct(reduction(pre_objects, post_objects))} |")
        post_max = item["post"]["stats"]["working_set_max"]
        headroom = limit_mib - post_max if post_max is not None else None
        lines.extend([
            "",
            f"Post maximum working set: **{fmt(post_max)} MiB**; headroom: **{fmt(headroom)} MiB**.",
            f"CPU time: {fmt(item['pre']['stats']['cpu_delta'])} → {fmt(item['post']['stats']['cpu_delta'])} seconds. Reconciles: {fmt(item['pre']['stats']['reconcile_delta'])} → {fmt(item['post']['stats']['reconcile_delta'])}.",
        ])
    lines.extend(["", "## Retained-type analysis", "", "| Allocation path | Workload | Pre | Post |", "|---|---|---:|---:|"])
    for item in results:
        for target in TYPE_PATHS:
            pre_value = item["pre"]["profile"]["paths"].get(target)
            post_value = item["post"]["profile"]["paths"].get(target)
            if pre_value is None and post_value is None:
                continue
            def path_value(value: dict[str, str] | None) -> str:
                return "Not sampled" if value is None else f"{value['flat']} flat / {value['cum']} cumulative"
            lines.append(f"| `{target}` | {item['label']} | {path_value(pre_value)} | {path_value(post_value)} |")
    lines.extend([
        "",
        "`pprof` attributes live allocations to allocation stacks; it is not an object-by-object deep-size census.",
        "",
        "## Method",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Pre source | `{config['pre_commit']}` |",
        f"| Post source | `{config['post_commit']}` |",
        f"| Sampling | {config['benchmark']['samples']} samples; {config['benchmark']['interval_seconds']} seconds apart |",
        f"| Production limit | {limit_text} |",
        f"| Pre profile limit | {config['operator'].get('pre_profile_memory_limit', 'Not recorded')} |",
        f"| Pre image | `{config['images'].get('pre') or 'Not recorded'}` |",
        f"| Post image | `{config['images'].get('post') or 'Not recorded'}` |",
        "",
        "## Evidence",
        "",
        "| Workload | Pre samples | Post samples | Pre profile | Post profile |",
        "|---|---|---|---|---|",
    ])
    for item in results:
        base = f"scenarios/{item['name']}"
        lines.append(f"| {item['label']} | [TSV]({base}/pre/samples.tsv) | [TSV]({base}/post/samples.tsv) | [in-use space]({base}/pre/heap-inuse-space.txt) | [in-use space]({base}/post/heap-inuse-space.txt) |")
    health = load_json(run_dir / "cluster" / "after" / "health.json", None)
    if not health:
        missing.append("cluster/after/health.json")
    lines.extend(["", "## Status", ""])
    if missing:
        lines.append("- Result: **incomplete**.")
        lines.append("- Missing evidence: " + ", ".join(f"`{item}`" for item in missing) + ".")
    else:
        lines.append("- Result: **complete for configured scenarios**.")
    lines.append(f"- Cluster restoration/health: {'recorded' if health else 'Not recorded' }.")
    report = run_dir / "dashboard-cache-testing-summary.md"
    report.write_text("\n".join(lines) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        run_dir = args.run_dir.resolve()
        config = load_json(run_dir / "resolved-config.json")
        if not isinstance(config, dict):
            fail("missing or invalid resolved-config.json")
        results, missing = build_results(run_dir, config)
        print(render(run_dir, config, results, missing))
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
