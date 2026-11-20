#!/usr/bin/env python3
"""Populate an OpenShift cluster with lightweight, RHOAI-like test objects.

The script streams generated objects to one `oc apply` process.  It waits only
for API acceptance; it never waits for Deployments or Pods to become ready.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from typing import Any, Optional, TextIO


MANAGED_BY = "rhoai-scale-populator"
DEFAULT_PREFIX = "rhoai-scale"
MAX_CONFIGMAP_PAYLOAD_KIB = 900


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create synthetic RHOAI/ODH project namespaces and optionally "
            "populate each one with lightweight Kubernetes resources."
        )
    )
    parser.add_argument(
        "-n",
        "--namespaces",
        type=int,
        required=True,
        metavar="COUNT",
        help="number of new namespaces to generate",
    )
    populate = parser.add_mutually_exclusive_group()
    populate.add_argument(
        "--populate-resources",
        action="store_true",
        help="add a workbench-like resource bundle to every namespace",
    )
    populate.add_argument(
        "--no-populate-resources",
        action="store_false",
        dest="populate_resources",
        help="create namespaces only (the default)",
    )
    parser.set_defaults(populate_resources=False)
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help=f"namespace and fixture name prefix (default: {DEFAULT_PREFIX})",
    )
    parser.add_argument(
        "--deployment-replicas",
        type=int,
        default=0,
        metavar="COUNT",
        help="replicas per generated Deployment (default: 0, to avoid Pods)",
    )
    parser.add_argument(
        "--configmaps-per-namespace",
        type=int,
        default=1,
        metavar="COUNT",
        help="ConfigMaps generated per populated namespace (default: 1)",
    )
    parser.add_argument(
        "--configmap-payload-kib",
        type=int,
        default=0,
        metavar="KIB",
        help=(
            "optional filler payload per ConfigMap, 0-%d KiB (default: 0)"
            % MAX_CONFIGMAP_PAYLOAD_KIB
        ),
    )
    parser.add_argument(
        "--allow-existing-namespaces",
        action="store_true",
        help="allow idempotent application into namespaces that already exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write generated manifest documents to stdout without calling oc",
    )
    parser.add_argument(
        "--verbose-oc",
        action="store_true",
        help="show per-object output from oc apply",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.namespaces < 1:
        raise ValueError("--namespaces must be at least 1")
    if args.deployment_replicas < 0:
        raise ValueError("--deployment-replicas cannot be negative")
    if args.configmaps_per_namespace < 1:
        raise ValueError("--configmaps-per-namespace must be at least 1")
    if not 0 <= args.configmap_payload_kib <= MAX_CONFIGMAP_PAYLOAD_KIB:
        raise ValueError(
            f"--configmap-payload-kib must be between 0 and "
            f"{MAX_CONFIGMAP_PAYLOAD_KIB}"
        )
    if len(args.prefix) > 45:
        raise ValueError("--prefix must be at most 45 characters")
    if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", args.prefix):
        raise ValueError(
            "--prefix must be a lowercase DNS label: letters, digits and hyphens"
        )


def run_oc(*arguments: str) -> str:
    result = subprocess.run(
        ["oc", *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def preflight(args: argparse.Namespace, namespace_names: list[str]) -> None:
    if shutil.which("oc") is None:
        raise RuntimeError("oc was not found in PATH")
    try:
        user = run_oc("whoami")
        server = run_oc("whoami", "--show-server")
        namespaces = json.loads(run_oc("get", "namespaces", "-o", "json"))
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or str(exc)
        raise RuntimeError(f"oc preflight failed: {detail}") from exc

    print(f"Target: {server} as {user}", file=sys.stderr)
    existing = {item["metadata"]["name"] for item in namespaces["items"]}
    collisions = [name for name in namespace_names if name in existing]
    if collisions and not args.allow_existing_namespaces:
        sample = ", ".join(collisions[:10])
        suffix = " ..." if len(collisions) > 10 else ""
        raise RuntimeError(
            f"{len(collisions)} target namespace(s) already exist: {sample}{suffix}. "
            "Choose another --prefix or pass --allow-existing-namespaces."
        )


def labels(prefix: str, index: int) -> dict[str, str]:
    return {
        "app.kubernetes.io/managed-by": MANAGED_BY,
        "app.kubernetes.io/part-of": "rhoai-scale-fixture",
        "scale.opendatahub.io/fixture": prefix,
        "scale.opendatahub.io/index": f"{index:04d}",
    }


def metadata(
    name: str,
    namespace: Optional[str],
    common_labels: dict[str, str],
    extra_labels: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    object_labels = dict(common_labels)
    if extra_labels:
        object_labels.update(extra_labels)
    result: dict[str, Any] = {"name": name, "labels": object_labels}
    if namespace:
        result["namespace"] = namespace
    return result


def encoded(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def resource_bundle(
    namespace: str,
    prefix: str,
    index: int,
    replicas: int,
    configmaps_per_namespace: int,
    payload_kib: int,
) -> Iterator[dict[str, Any]]:
    common = labels(prefix, index)
    instance = f"ds-workbench-{index:04d}"
    service_account = f"workbench-{index:04d}"
    app_labels = {
        "app.kubernetes.io/name": "data-science-workbench",
        "app.kubernetes.io/instance": instance,
        "app.kubernetes.io/component": "workbench",
        "opendatahub.io/dashboard": "true",
    }

    yield {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": metadata(service_account, namespace, common, app_labels),
    }

    first_configmap = f"{instance}-config-01"
    payload = "x" * (payload_kib * 1024)
    for number in range(1, configmaps_per_namespace + 1):
        config_data = {
            "PROJECT_DISPLAY_NAME": f"Data Science Project {index:04d}",
            "NOTEBOOK_IMAGE": "registry.access.redhat.com/ubi9/ubi-minimal:latest",
            "MODEL_ENDPOINT": f"http://model-server-{index:04d}.{namespace}.svc:8080",
            "PIPELINE_NAME": f"training-pipeline-{index:04d}",
        }
        if payload:
            config_data["SYNTHETIC_PAYLOAD"] = payload
        yield {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": metadata(
                f"{instance}-config-{number:02d}", namespace, common, app_labels
            ),
            "data": config_data,
        }

    secret_name = f"{instance}-object-storage"
    yield {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": metadata(secret_name, namespace, common, app_labels),
        "type": "Opaque",
        "data": {
            "AWS_ACCESS_KEY_ID": encoded(f"scale-access-{index:04d}"),
            "AWS_SECRET_ACCESS_KEY": encoded(
                f"synthetic-not-a-real-secret-{index:04d}"
            ),
            "AWS_DEFAULT_REGION": encoded("us-east-1"),
        },
    }

    yield {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": metadata(instance, namespace, common, app_labels),
        "spec": {
            "replicas": replicas,
            "selector": {"matchLabels": {"app.kubernetes.io/instance": instance}},
            "template": {
                "metadata": {"labels": {**common, **app_labels}},
                "spec": {
                    "serviceAccountName": service_account,
                    "containers": [
                        {
                            "name": "workbench",
                            "image": "registry.access.redhat.com/ubi9/ubi-minimal:latest",
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["/bin/sh", "-c", "sleep infinity"],
                            "ports": [{"name": "notebook", "containerPort": 8888}],
                            "envFrom": [
                                {"configMapRef": {"name": first_configmap}},
                                {"secretRef": {"name": secret_name}},
                            ],
                            "resources": {
                                "requests": {"cpu": "25m", "memory": "64Mi"},
                                "limits": {"cpu": "200m", "memory": "256Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                                "runAsNonRoot": True,
                                "runAsUser": 1001,
                            },
                        }
                    ],
                    "securityContext": {
                        "seccompProfile": {"type": "RuntimeDefault"}
                    },
                },
            },
        },
    }

    yield {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": metadata(instance, namespace, common, app_labels),
        "spec": {
            "selector": {"app.kubernetes.io/instance": instance},
            "ports": [{"name": "notebook", "port": 8888, "targetPort": "notebook"}],
        },
    }

    yield {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": metadata(
            f"{instance}-allow-ingress", namespace, common, app_labels
        ),
        "spec": {
            "podSelector": {"matchLabels": {"app.kubernetes.io/instance": instance}},
            "policyTypes": ["Ingress"],
            "ingress": [
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "network.openshift.io/policy-group": "ingress"
                                }
                            }
                        },
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": namespace
                                }
                            }
                        },
                    ]
                }
            ],
        },
    }

    yield {
        "apiVersion": "policy/v1",
        "kind": "PodDisruptionBudget",
        "metadata": metadata(f"{instance}-pdb", namespace, common, app_labels),
        "spec": {
            "maxUnavailable": 1,
            "selector": {"matchLabels": {"app.kubernetes.io/instance": instance}},
        },
    }

    role_name = f"{instance}-reader"
    yield {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "Role",
        "metadata": metadata(role_name, namespace, common, app_labels),
        "rules": [
            {
                "apiGroups": [""],
                "resources": ["configmaps", "secrets", "services", "pods"],
                "verbs": ["get", "list", "watch"],
            }
        ],
    }

    yield {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": metadata(role_name, namespace, common, app_labels),
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "Role",
            "name": role_name,
        },
        "subjects": [
            {"kind": "ServiceAccount", "name": service_account, "namespace": namespace}
        ],
    }


def generated_objects(args: argparse.Namespace) -> Iterator[dict[str, Any]]:
    width = max(4, len(str(args.namespaces)))
    for index in range(1, args.namespaces + 1):
        namespace = f"{args.prefix}-{index:0{width}d}"
        common = labels(args.prefix, index)
        yield {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                **metadata(namespace, None, common),
                "annotations": {
                    "openshift.io/display-name": f"RHOAI Scale Project {index:04d}",
                    "openshift.io/description": (
                        "Synthetic data science project for dashboard-operator "
                        "cache scale validation"
                    ),
                },
                "labels": {
                    **common,
                    "opendatahub.io/dashboard": "true",
                },
            },
        }
        if args.populate_resources:
            yield from resource_bundle(
                namespace,
                args.prefix,
                index,
                args.deployment_replicas,
                args.configmaps_per_namespace,
                args.configmap_payload_kib,
            )


def write_documents(objects: Iterator[dict[str, Any]], output: TextIO) -> None:
    first = True
    for obj in objects:
        if not first:
            output.write("\n---\n")
        json.dump(obj, output, separators=(",", ":"))
        first = False
    output.write("\n")


def apply_objects(args: argparse.Namespace) -> None:
    command = [
        "oc",
        "apply",
        "--server-side",
        f"--field-manager={MANAGED_BY}",
        "-f",
        "-",
    ]
    stdout = None if args.verbose_oc else subprocess.DEVNULL
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=stdout,
        text=True,
    )
    assert process.stdin is not None
    try:
        write_documents(generated_objects(args), process.stdin)
        process.stdin.close()
        return_code = process.wait()
    except (BrokenPipeError, KeyboardInterrupt):
        process.stdin.close()
        process.terminate()
        process.wait()
        raise RuntimeError("oc apply was interrupted or closed its input early")
    if return_code != 0:
        raise RuntimeError(f"oc apply failed with exit code {return_code}")


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
        width = max(4, len(str(args.namespaces)))
        namespace_names = [
            f"{args.prefix}-{index:0{width}d}"
            for index in range(1, args.namespaces + 1)
        ]

        if args.dry_run:
            write_documents(generated_objects(args), sys.stdout)
            return 0

        preflight(args, namespace_names)
        namespaced_count = 8 + args.configmaps_per_namespace
        object_count = args.namespaces * (
            1 + (namespaced_count if args.populate_resources else 0)
        )
        print(
            f"Submitting {object_count} object(s) across "
            f"{args.namespaces} namespace(s); no rollout wait will be performed.",
            file=sys.stderr,
        )
        apply_objects(args)
        print(
            f"Submitted {object_count} object(s). API acceptance completed; "
            "Deployment readiness was not checked.",
            file=sys.stderr,
        )
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
