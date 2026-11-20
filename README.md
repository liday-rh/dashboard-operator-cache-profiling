# Dashboard Operator Cache Profiling

Reproducible OpenShift load generation, memory benchmarking, and heap-profile evidence for dashboard-operator cache behavior.

## Contents

- [Dashboard cache performance skill](.agents/skills/dashboard-cache-performance/SKILL.md): reusable pre/post orchestration with timestamped result directories.
- [`scripts/`](scripts/README.md): cluster population, benchmark collection, heap collection, and chart rendering tools.
- [`outputs/dashboard-cache-testing-summary.md`](outputs/dashboard-cache-testing-summary.md): consolidated test results and visual comparisons.
- [`outputs/dashboard-cache-test-plan.md`](outputs/dashboard-cache-test-plan.md): complete test plan and acceptance criteria.
- [`outputs/`](outputs/): raw TSV samples, pprof data, reports, and charts.
- [`patches/`](patches/README.md): diagnostic-only pprof changes for the exact pre/post source revisions.

## Quick start

Prerequisites:

- Python 3
- `oc` in `PATH`
- An active `oc` login to a disposable OpenShift cluster

Preview a small fixture without changing a cluster:

```sh
python3 scripts/populate-rhoai-scale-cluster.py \
  --namespaces 2 \
  --populate-resources \
  --dry-run
```

Create the 350-namespace scale fixture:

```sh
python3 scripts/populate-rhoai-scale-cluster.py \
  --namespaces 350 \
  --prefix rhoai-scale \
  --populate-resources \
  --deployment-replicas 0
```

See [`scripts/README.md`](scripts/README.md) for all population modes, cleanup, and profiling commands.

For a complete configurable pre/post run, invoke `$dashboard-cache-performance` with the source checkout, pre/post commits, cluster kubeconfig, and workload parameters. Results are created under `output/results/<UTC datetime>-<run name>/`.

## Safety

Use a dedicated cluster. Generated namespaces are labelled with `scale.opendatahub.io/fixture=<prefix>` and may be removed together by that label. Deployments default to zero replicas. The generator waits only for API acceptance and does not wait for workload readiness.

Cluster credentials and temporary source worktrees are intentionally excluded from Git.
