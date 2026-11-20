# Dashboard Operator Cache Profiling

Reproducible pre/post memory and cache profiling for the dashboard operator on a disposable OpenShift cluster.

The `$dashboard-cache-performance` skill prepares identical synthetic workloads, benchmarks two immutable operator revisions, collects runtime and heap evidence, restores the cluster, and generates a human-readable comparison report.

## Requirements

- Codex opened from this repository so the project skill is available.
- A dedicated, non-production OpenShift cluster.
- `oc` logged in through a kubeconfig file.
- A local dashboard source checkout containing both test revisions.
- Python 3, `jq`, and `pprof` available locally.
- A supported method for building and pushing dashboard-operator images.

The pre and post revisions must resolve to different commits. Images used for collection must be immutable digest references. Retained-heap profiling also requires the diagnostic loopback-only pprof endpoint.

## Run the benchmark

Open Codex in this repository and invoke the skill with the source checkout, revisions, kubeconfig, and workload parameters. For example:

```text
Use $dashboard-cache-performance to compare the dashboard operator cache behavior.

Source checkout: /path/to/odh-dashboard
Pre commit: <pre-optimization-commit-or-ref>
Post commit: <post-optimization-commit-or-ref>
Kubeconfig: /path/to/kubeconfig

Run these workloads sequentially:
1. 350 namespaces populated with the standard RHOAI-like resource bundle.
2. 90 namespaces populated with resources, including two 800 KiB ConfigMaps per namespace.

Use 20 samples at 30-second intervals, test both revisions at the 256Mi
production memory limit, collect forced-GC pprof evidence, clean up each
workload, restore the cluster, and render the final report.
```

The workload is configurable. Each scenario can set its namespace count, whether resources are populated, Deployment replicas, ConfigMaps per namespace, and payload size. Sampling intervals, sample counts, memory limits, operator location, and pre/post image digests are also configurable.

The skill creates a resolved run configuration from [the example configuration](.agents/skills/dashboard-cache-performance/assets/run-config.example.json). See the [skill instructions](.agents/skills/dashboard-cache-performance/SKILL.md) for the execution contract and safety requirements.

## What the skill does

1. Resolves the pre and post refs to exact commit SHAs.
2. Creates a uniquely named result directory and snapshots the cluster.
3. Builds or verifies immutable diagnostic images.
4. Populates each configured workload with run-specific labels.
5. Runs matching pre/post sampling and forced-GC heap collection.
6. Records OOM, restart, resource-limit, pod, Deployment, and operator-log evidence.
7. Cleans up generated namespaces, restores the original deployment, and verifies cluster health.
8. Renders the comparison report and charts.

## Results

Every run is written to a new UTC-dated directory:

```text
output/results/<UTC-datetime>-<run-name>/
```

The primary report is:

```text
output/results/<run-id>/dashboard-cache-testing-summary.md
```

A completed result directory contains:

```text
<run-id>/
├── dashboard-cache-testing-summary.md
├── resolved-config.json
├── charts/
│   ├── cache-summary-comparison.svg
│   └── cache-working-set-series.svg
├── cluster/
│   ├── before/
│   └── after/health.json
└── scenarios/
    └── <scenario>/
        ├── inventory.json
        ├── population.json
        ├── pre/
        │   ├── samples.tsv
        │   ├── environment.json
        │   ├── operator.log
        │   └── heap-*
        └── post/
            └── ...
```

Open `dashboard-cache-testing-summary.md` for the benchmark summary, charts, detailed metrics, retained-type analysis, method, and evidence links. Share the complete run directory—not only the Markdown file—so its relative chart, TSV, and profile links remain usable.

Missing evidence is shown as `Not recorded`, and a run without final cluster-health evidence is marked incomplete.

## Repository layout

- [`.agents/skills/dashboard-cache-performance/`](.agents/skills/dashboard-cache-performance/): benchmark skill, configuration, workflow, and report renderer.
- [`scripts/`](scripts/): population, collection, cleanup, and chart utilities used by the skill.
- [`output/results/`](output/results/): timestamped output from new skill runs.
- [`outputs/`](outputs/): reference evidence and reports from the original benchmark.
- [`patches/`](patches/): diagnostic-only pprof changes for the profiled source revisions.

## Safety

Run only against a dedicated test cluster. The skill uses unique fixture labels, requires exact-prefix confirmation before cleanup, never exposes pprof outside the pod loopback interface, and preserves missing evidence rather than inferring results. Kubeconfig contents and temporary source worktrees are excluded from Git.
