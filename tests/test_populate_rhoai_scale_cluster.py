from __future__ import annotations

import argparse
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "populate-rhoai-scale-cluster.py"
SPEC = importlib.util.spec_from_file_location("populate_rhoai_scale_cluster", SCRIPT)
assert SPEC and SPEC.loader
POPULATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POPULATOR)


class PopulateRhoaiScaleClusterTest(unittest.TestCase):
    def test_create_dry_run_retains_default_prefix(self) -> None:
        stdout = io.StringIO()
        argv = [str(SCRIPT), "--namespaces", "1", "--dry-run"]

        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            sys, "stdout", stdout
        ):
            result = POPULATOR.main()

        self.assertEqual(0, result)
        self.assertIn('"name":"rhoai-scale-0001"', stdout.getvalue())

    def test_cleanup_requires_explicit_prefix(self) -> None:
        args = argparse.Namespace(
            cleanup=True,
            prefix=None,
            namespaces=None,
            deployment_replicas=0,
            configmaps_per_namespace=1,
            configmap_payload_kib=0,
        )

        with self.assertRaisesRegex(ValueError, "explicit --prefix"):
            POPULATOR.validate_args(args)

    def test_cleanup_dry_run_lists_without_deleting(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_run_oc(*arguments: str) -> str:
            calls.append(arguments)
            if arguments == ("whoami",):
                return "test-user"
            if arguments == ("whoami", "--show-server"):
                return "https://api.example.test:6443"
            return '{"items":[{"metadata":{"name":"fixture-0001"}}]}'

        args = argparse.Namespace(prefix="fixture", dry_run=True)
        with mock.patch.object(
            POPULATOR.shutil, "which", return_value="/usr/bin/oc"
        ), mock.patch.object(POPULATOR, "run_oc", side_effect=fake_run_oc):
            POPULATOR.cleanup_fixture(args)

        self.assertFalse(any(call and call[0] == "delete" for call in calls))

    def test_cleanup_deletes_exact_generated_labels_without_waiting(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_run_oc(*arguments: str) -> str:
            calls.append(arguments)
            if arguments == ("whoami",):
                return "test-user"
            if arguments == ("whoami", "--show-server"):
                return "https://api.example.test:6443"
            if arguments[0] == "get":
                return '{"items":[{"metadata":{"name":"fixture-0001"}}]}'
            return 'namespace "fixture-0001" deleted'

        args = argparse.Namespace(prefix="fixture", dry_run=False)
        selector = (
            "scale.opendatahub.io/fixture=fixture,"
            "app.kubernetes.io/managed-by=rhoai-scale-populator"
        )
        expected = (
            "delete",
            "namespaces",
            "-l",
            selector,
            "--wait=false",
        )
        with mock.patch.object(
            POPULATOR.shutil, "which", return_value="/usr/bin/oc"
        ), mock.patch.object(POPULATOR, "run_oc", side_effect=fake_run_oc):
            POPULATOR.cleanup_fixture(args)

        self.assertIn(expected, calls)


if __name__ == "__main__":
    unittest.main()
