#!/usr/bin/env python3
"""Validate a performance-test config and create a unique run directory."""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NAME_RE = re.compile(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?")


def fail(message: str) -> None:
    raise ValueError(message)


def project_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "scripts" / "populate-rhoai-scale-cluster.py").is_file():
            return candidate
    fail("could not locate the test-project root")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"unable to read config {path}: {exc}")
    if not isinstance(value, dict):
        fail("config root must be an object")
    return value


def resolve_commit(source_root: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(f"cannot resolve commit {ref!r}: {result.stderr.strip()}")
    return result.stdout.strip()


def positive_int(value: Any, field: str, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        fail(f"{field} must be an integer >= {minimum}")
    return value


def validate(config: dict[str, Any], root: Path) -> dict[str, Any]:
    resolved = copy.deepcopy(config)
    if resolved.get("schema_version", 1) != 1:
        fail("unsupported schema_version")

    source_root = Path(str(resolved.get("source_root", ""))).expanduser()
    if not source_root.is_absolute():
        source_root = (root / source_root).resolve()
    if not (source_root / ".git").exists():
        fail(f"source_root is not a Git checkout: {source_root}")
    resolved["source_root"] = str(source_root)

    for key in ("pre_commit", "post_commit"):
        ref = resolved.get(key)
        if not isinstance(ref, str) or not ref:
            fail(f"{key} is required")
        resolved[key] = resolve_commit(source_root, ref)
    if resolved["pre_commit"] == resolved["post_commit"]:
        fail("pre_commit and post_commit resolve to the same commit")

    kubeconfig = Path(str(resolved.get("kubeconfig", ""))).expanduser()
    if not kubeconfig.is_absolute():
        kubeconfig = (root / kubeconfig).resolve()
    if not kubeconfig.is_file():
        fail(f"kubeconfig does not exist: {kubeconfig}")
    resolved["kubeconfig"] = str(kubeconfig)

    benchmark = resolved.setdefault("benchmark", {})
    benchmark["samples"] = positive_int(benchmark.get("samples", 20), "benchmark.samples")
    benchmark["interval_seconds"] = positive_int(
        benchmark.get("interval_seconds", 30), "benchmark.interval_seconds", 0
    )
    benchmark["stabilization_seconds"] = positive_int(
        benchmark.get("stabilization_seconds", 120),
        "benchmark.stabilization_seconds",
        0,
    )
    benchmark["collect_pprof"] = bool(benchmark.get("collect_pprof", True))

    images = resolved.setdefault("images", {})
    for variant in ("pre", "post"):
        image = images.get(variant, "")
        if image and "@sha256:" not in image:
            fail(f"images.{variant} must be an immutable digest reference")
        images[variant] = image

    operator = resolved.setdefault("operator", {})
    operator_defaults = {
        "namespace": "redhat-ods-applications",
        "deployment": "dashboard-operator",
        "container": "manager",
        "production_memory_limit": "256Mi",
        "pre_profile_memory_limit": "1Gi",
    }
    for key, default in operator_defaults.items():
        value = operator.get(key, default)
        if not isinstance(value, str) or not value.strip():
            fail(f"operator.{key} must be a non-empty string")
        operator[key] = value

    scenarios = resolved.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        fail("at least one scenario is required")
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            fail(f"scenarios[{index}] must be an object")
        name = scenario.get("name")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            fail(f"scenarios[{index}].name must be a lowercase DNS-style name")
        if name in seen:
            fail(f"duplicate scenario name: {name}")
        seen.add(name)
        scenario["label"] = str(scenario.get("label", name))
        scenario["namespaces"] = positive_int(
            scenario.get("namespaces"), f"scenarios[{index}].namespaces"
        )
        scenario["populate_resources"] = bool(scenario.get("populate_resources", False))
        scenario["deployment_replicas"] = positive_int(
            scenario.get("deployment_replicas", 0),
            f"scenarios[{index}].deployment_replicas",
            0,
        )
        scenario["configmaps_per_namespace"] = positive_int(
            scenario.get("configmaps_per_namespace", 1),
            f"scenarios[{index}].configmaps_per_namespace",
        )
        payload = positive_int(
            scenario.get("configmap_payload_kib", 0),
            f"scenarios[{index}].configmap_payload_kib",
            0,
        )
        if payload > 900:
            fail(f"scenarios[{index}].configmap_payload_kib exceeds 900")
        scenario["configmap_payload_kib"] = payload
        prefix = str(scenario.get("prefix", name))
        if not NAME_RE.fullmatch(prefix):
            fail(f"scenarios[{index}].prefix must be a lowercase DNS-style name")
        scenario["prefix"] = prefix

    run_name = str(resolved.get("run_name", "dashboard-cache"))
    run_slug = re.sub(r"[^a-z0-9]+", "-", run_name.lower()).strip("-") or "run"
    resolved["run_name"] = run_name
    resolved["project_root"] = str(root)
    resolved["run_slug"] = run_slug
    return resolved


def unique_run_dir(root: Path, config: dict[str, Any]) -> tuple[Path, str, str]:
    output_root = Path(str(config.get("output_root", "output/results"))).expanduser()
    if not output_root.is_absolute():
        output_root = (root / output_root).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}-{config['run_slug']}"
    candidate = output_root / base
    suffix = 2
    while candidate.exists():
        candidate = output_root / f"{base}-{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate, candidate.name, stamp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        root = project_root()
        resolved = validate(load_json(args.config.resolve()), root)
        run_dir, run_id, stamp = unique_run_dir(root, resolved)
        resolved["run_id"] = run_id
        resolved["created_at"] = stamp
        resolved["run_dir"] = str(run_dir)
        for scenario in resolved["scenarios"]:
            max_prefix = 45 - 1 - len(stamp.lower())
            base = scenario["prefix"][:max_prefix].rstrip("-")
            scenario["resolved_prefix"] = f"{base}-{stamp.lower()}"
            for variant in ("pre", "post"):
                (run_dir / "scenarios" / scenario["name"] / variant).mkdir(
                    parents=True
                )
        (run_dir / "charts").mkdir()
        (run_dir / "cluster" / "before").mkdir(parents=True)
        (run_dir / "resolved-config.json").write_text(
            json.dumps(resolved, indent=2, sort_keys=True) + "\n"
        )
        print(run_dir)
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
