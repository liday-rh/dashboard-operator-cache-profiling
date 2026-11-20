#!/usr/bin/env python3
"""Run deterministic population, collection, and cleanup phases."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RESOURCES = (
    "namespaces",
    "configmaps",
    "secrets",
    "deployments",
    "services",
    "networkpolicies",
    "poddisruptionbudgets",
    "roles",
    "rolebindings",
    "serviceaccounts",
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def config_path(run_dir: Path) -> Path:
    path = run_dir.resolve() / "resolved-config.json"
    if not path.is_file():
        fail(f"missing resolved config: {path}")
    return path


def load_config(run_dir: Path) -> dict[str, Any]:
    return json.loads(config_path(run_dir).read_text())


def save_config(run_dir: Path, config: dict[str, Any]) -> None:
    config_path(run_dir).write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")


def scenario(config: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [item for item in config["scenarios"] if item["name"] == name]
    if len(matches) != 1:
        fail(f"unknown scenario: {name}")
    return matches[0]


def environment(config: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env["KUBECONFIG"] = config["kubeconfig"]
    return env


def execute(
    command: list[str],
    *,
    env: dict[str, str],
    output: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        env=env,
        text=True,
        stdout=subprocess.PIPE if output else None,
        stderr=None,
        check=False,
    )
    if output is not None:
        output.write_text(result.stdout or "")
    if check and result.returncode != 0:
        fail(f"command failed ({result.returncode}): {shlex.join(command)}")
    return result


def oc_json(config: dict[str, Any], arguments: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        ["oc", "--kubeconfig", config["kubeconfig"], *arguments, "-o", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(result.stderr.strip() or f"oc {' '.join(arguments)} failed")
    return json.loads(result.stdout)


def collect_inventory(config: dict[str, Any], item: dict[str, Any], target: Path) -> None:
    selector = f"scale.opendatahub.io/fixture={item['resolved_prefix']}"
    counts: dict[str, int] = {}
    names: dict[str, list[str]] = {}
    configmap_data_bytes = 0
    for resource in RESOURCES:
        args = ["get", resource]
        if resource != "namespaces":
            args.append("-A")
        args.extend(["-l", selector])
        data = oc_json(config, args)
        counts[resource] = len(data.get("items", []))
        names[resource] = [entry["metadata"]["name"] for entry in data.get("items", [])]
        if resource == "configmaps":
            configmap_data_bytes = sum(
                len(str(value).encode())
                for entry in data.get("items", [])
                for value in entry.get("data", {}).values()
            )
    target.write_text(
        json.dumps(
            {
                "captured_at": now(),
                "selector": selector,
                "counts": counts,
                "names": names,
                "configmap_data_bytes": configmap_data_bytes,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def populate(
    run_dir: Path, config: dict[str, Any], name: str, *, dry_run: bool = False
) -> None:
    item = scenario(config, name)
    script = Path(config["project_root"]) / "scripts" / "populate-rhoai-scale-cluster.py"
    command = [
        sys.executable,
        str(script),
        "--namespaces",
        str(item["namespaces"]),
        "--prefix",
        item["resolved_prefix"],
        "--deployment-replicas",
        str(item["deployment_replicas"]),
        "--configmaps-per-namespace",
        str(item["configmaps_per_namespace"]),
        "--configmap-payload-kib",
        str(item["configmap_payload_kib"]),
    ]
    command.append("--populate-resources" if item["populate_resources"] else "--no-populate-resources")
    if dry_run:
        command.append("--dry-run")
    started = now()
    scenario_dir = run_dir / "scenarios" / name
    execute(
        command,
        env=environment(config),
        output=scenario_dir / "generated-manifest.json" if dry_run else None,
    )
    if not dry_run:
        collect_inventory(config, item, scenario_dir / "inventory.json")
    (scenario_dir / "population.json").write_text(
        json.dumps(
            {
                "started_at": started,
                "completed_at": now(),
                "command": command,
                "prefix": item["resolved_prefix"],
                "dry_run": dry_run,
            },
            indent=2,
        )
        + "\n"
    )


def set_image(run_dir: Path, config: dict[str, Any], variant: str, image: str) -> None:
    if "@sha256:" not in image:
        fail("image must be an immutable digest reference")
    config["images"][variant] = image
    save_config(run_dir, config)


def operator_pod(config: dict[str, Any], expected_image: str) -> dict[str, Any]:
    namespace = config["operator"]["namespace"]
    deployment = config["operator"]["deployment"]
    data = oc_json(config, ["get", "pods", "-n", namespace])
    matches = []
    for pod in data.get("items", []):
        name = pod["metadata"]["name"]
        images = [container.get("image") for container in pod["spec"].get("containers", [])]
        if name.startswith(f"{deployment}-") and pod["status"].get("phase") == "Running" and expected_image in images:
            matches.append(pod)
    if len(matches) != 1:
        fail(f"expected one running {deployment} pod using {expected_image}; found {len(matches)}")
    return matches[0]


def collect(run_dir: Path, config: dict[str, Any], name: str, variant: str) -> None:
    scenario(config, name)
    image = config["images"].get(variant, "")
    if "@sha256:" not in image:
        fail(f"record an immutable {variant} image before collection")
    target = run_dir / "scenarios" / name / variant
    project = Path(config["project_root"])
    benchmark = config["benchmark"]
    collector = project / "scripts" / "collect-dashboard-cache-benchmark.sh"
    execute(
        [
            str(collector),
            config["kubeconfig"],
            str(target / "samples.tsv"),
            str(benchmark["samples"]),
            str(benchmark["interval_seconds"]),
            image,
            config["operator"]["namespace"],
            config["operator"]["deployment"],
            config["operator"]["container"],
        ],
        env=environment(config),
    )
    pod = operator_pod(config, image)
    namespace = config["operator"]["namespace"]
    pod_name = pod["metadata"]["name"]
    deployment = config["operator"]["deployment"]
    container = config["operator"]["container"]
    deployment_json = oc_json(config, ["get", "deployment", deployment, "-n", namespace])
    (target / "pod.json").write_text(json.dumps(pod, indent=2, sort_keys=True) + "\n")
    (target / "deployment.json").write_text(
        json.dumps(deployment_json, indent=2, sort_keys=True) + "\n"
    )
    status = next((
        item
        for item in pod.get("status", {}).get("containerStatuses", [])
        if item.get("name") == container
    ), None)
    if status is None:
        fail(f"container status {container!r} not found in operator pod")
    resources = next((
        item.get("resources", {})
        for item in pod["spec"]["containers"]
        if item["name"] == container
    ), None)
    if resources is None:
        fail(f"container {container!r} not found in operator pod")
    (target / "environment.json").write_text(
        json.dumps(
            {
                "captured_at": now(),
                "commit": config[f"{variant}_commit"],
                "image": image,
                "pod": pod_name,
                "restart_count": status.get("restartCount"),
                "resources": resources,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    execute(
        [
            "oc",
            "--kubeconfig",
            config["kubeconfig"],
            "logs",
            "-n",
            namespace,
            pod_name,
            "-c",
            container,
        ],
        env=environment(config),
        output=target / "operator.log",
        check=False,
    )
    if benchmark["collect_pprof"]:
        pprof = project / "scripts" / "collect-dashboard-heap-profile.sh"
        execute(
            [
                str(pprof),
                config["kubeconfig"],
                namespace,
                pod_name,
                str(target / "heap"),
                container,
            ],
            env=environment(config),
        )


def record_observation(
    run_dir: Path,
    config: dict[str, Any],
    name: str,
    variant: str,
    args: argparse.Namespace,
) -> None:
    scenario(config, name)
    target = run_dir / "scenarios" / name / variant / "observation.json"
    value: dict[str, Any] = {"recorded_at": now()}
    if target.exists():
        value.update(json.loads(target.read_text()))
    for key in ("memory_limit", "production_limit_result", "notes"):
        field = getattr(args, key)
        if field is not None:
            value[key] = field
    if args.oom_seconds is not None:
        value["oom_seconds"] = args.oom_seconds
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def cleanup(config: dict[str, Any], name: str, confirm_prefix: str) -> None:
    item = scenario(config, name)
    prefix = item["resolved_prefix"]
    if confirm_prefix != prefix:
        fail(f"confirmation does not match resolved prefix {prefix!r}")
    selector = f"scale.opendatahub.io/fixture={prefix}"
    data = oc_json(config, ["get", "namespaces", "-l", selector])
    names = [entry["metadata"]["name"] for entry in data.get("items", [])]
    if not names:
        print(f"no namespaces found for {selector}")
        return
    print(f"deleting {len(names)} namespaces for {selector}")
    execute(
        [
            "oc",
            "--kubeconfig",
            config["kubeconfig"],
            "delete",
            "namespaces",
            "-l",
            selector,
            "--wait=false",
        ],
        env=environment(config),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    populate_parser = sub.add_parser("populate")
    populate_parser.add_argument("--scenario", required=True)
    populate_parser.add_argument("--dry-run", action="store_true")
    inventory_parser = sub.add_parser("inventory")
    inventory_parser.add_argument("--scenario", required=True)
    image = sub.add_parser("set-image")
    image.add_argument("--variant", choices=("pre", "post"), required=True)
    image.add_argument("--image", required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--scenario", required=True)
    collect_parser.add_argument("--variant", choices=("pre", "post"), required=True)
    observation = sub.add_parser("record-observation")
    observation.add_argument("--scenario", required=True)
    observation.add_argument("--variant", choices=("pre", "post"), required=True)
    observation.add_argument("--memory-limit")
    observation.add_argument("--production-limit-result")
    observation.add_argument("--oom-seconds", type=int)
    observation.add_argument("--notes")
    cleanup_parser = sub.add_parser("cleanup")
    cleanup_parser.add_argument("--scenario", required=True)
    cleanup_parser.add_argument("--confirm-prefix", required=True)
    args = parser.parse_args()
    try:
        run_dir = args.run_dir.resolve()
        config = load_config(run_dir)
        if args.action == "populate":
            populate(run_dir, config, args.scenario, dry_run=args.dry_run)
        elif args.action == "inventory":
            item = scenario(config, args.scenario)
            collect_inventory(
                config, item, run_dir / "scenarios" / args.scenario / "inventory.json"
            )
        elif args.action == "set-image":
            set_image(run_dir, config, args.variant, args.image)
        elif args.action == "collect":
            collect(run_dir, config, args.scenario, args.variant)
        elif args.action == "record-observation":
            record_observation(run_dir, config, args.scenario, args.variant, args)
        elif args.action == "cleanup":
            cleanup(config, args.scenario, args.confirm_prefix)
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
