---
name: dashboard-cache-performance
description: Run reproducible pre/post dashboard-operator memory and cache performance tests on a disposable OpenShift cluster, including configurable commits, namespace/resource load, sampling, pprof collection, and timestamped reports. Use for dashboard cache benchmarks and scale regressions; do not use for ordinary unit tests or production-cluster diagnostics.
---

# Dashboard Cache Performance

Compare two immutable dashboard-operator revisions against identical synthetic workloads and produce a self-contained result directory with the canonical report layout.

## Required inputs

- Dedicated cluster and kubeconfig.
- Local dashboard source checkout.
- Pre and post commits or refs.
- One or more workload definitions.
- Image build/deployment route for the target cluster.

When the user supplies values conversationally, create a JSON config from `assets/run-config.example.json`. Read [references/configuration.md](references/configuration.md) before editing or validating configuration.

## Run contract

1. Read [references/workflow.md](references/workflow.md) and follow it completely.
2. Create a unique run with `scripts/create_run.py`; never write results directly into an earlier run.
3. Snapshot cluster state before mutation and define the exact restoration path.
4. Build or verify immutable pre/post images from the resolved commits. Retained profiles require loopback-only pprof.
5. For each scenario, invoke `scripts/run_phase.py populate`. This wrapper must call the project’s `scripts/populate-rhoai-scale-cluster.py`; do not replace it with ad hoc manifests.
6. Use the same load, sampling, stabilization, and collection method for both variants.
7. Attempt the configured production limit for both. Use a higher pre-profile limit only after recording that the pre image cannot survive at the production limit.
8. Collect benchmark TSV, pod/deployment evidence, logs, and forced-GC pprof for each variant.
9. Clean up only the exact run-specific labelled namespaces, restore the cluster snapshot, and verify health.
10. Render with `scripts/render_results.py` and validate the output against [references/report-contract.md](references/report-contract.md).

## Safety and evidence rules

- Never run against a production cluster.
- Resolve commits and images immutably; reject mutable-only provenance.
- Never expose pprof outside the pod loopback interface.
- Do not let scenario loads overlap.
- Require an exact resolved-prefix confirmation before cleanup.
- Preserve raw evidence and report missing data as `Not recorded`; never infer OOM timing, health, or profile totals.
- Keep kubeconfig contents outside the result directory.

The default output root is `output/results`; directories are named with UTC datetime plus the configured run name.
