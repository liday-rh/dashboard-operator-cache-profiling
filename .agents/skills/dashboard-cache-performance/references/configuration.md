# Configuration

Copy `assets/run-config.example.json`, then set the source checkout, commits, kubeconfig, workload, and benchmark values.

## Required fields

| Field | Meaning |
|---|---|
| `source_root` | Existing Git checkout containing dashboard-operator source |
| `pre_commit` | Commit or ref before the change |
| `post_commit` | Commit or ref after the change |
| `kubeconfig` | Logged-in disposable cluster kubeconfig |
| `scenarios` | One or more workload definitions |

Both refs are resolved to full commit SHAs when the run directory is created.

## Images

`images.pre` and `images.post` may be empty during setup. Before collection, record immutable digest references with `run_phase.py set-image`. Tags are rejected.

The image must correspond to the resolved commit. When retained heap data is required, it must expose pprof only on loopback. Build provenance belongs in the run directory.

## Workload fields

| Field | Default | Meaning |
|---|---:|---|
| `name` | required | Filesystem-safe scenario identifier |
| `label` | `name` | Report label |
| `prefix` | `name` | Base namespace prefix; the run ID is appended automatically |
| `namespaces` | required | Namespace count |
| `populate_resources` | `false` | Add the RHOAI-like resource bundle |
| `deployment_replicas` | `0` | Synthetic Deployment replicas |
| `configmaps_per_namespace` | `1` | ConfigMaps in each populated namespace |
| `configmap_payload_kib` | `0` | Data payload per ConfigMap, maximum 900 KiB |

Each run receives a unique resolved prefix, preventing collisions with earlier runs.

## Benchmark fields

| Field | Default | Meaning |
|---|---:|---|
| `samples` | `20` | Samples per image and scenario |
| `interval_seconds` | `30` | Delay between samples |
| `stabilization_seconds` | `120` | Minimum post-rollout stabilization time |
| `collect_pprof` | `true` | Collect forced-GC pprof data |

The standard acceptance run uses 20 samples over approximately 10 minutes. Longer steady-state windows can be configured without changing the workflow.

## Operator fields

| Field | Default | Meaning |
|---|---|---|
| `namespace` | `redhat-ods-applications` | Operator namespace |
| `deployment` | `dashboard-operator` | Operator Deployment and pod-name prefix |
| `container` | `manager` | Container used for metrics, status, and pprof |
| `production_memory_limit` | `256Mi` | Limit used for the pass/fail comparison |
| `pre_profile_memory_limit` | `1Gi` | Optional higher limit used only after recording a pre-image OOM |

## Output

`output_root` defaults to `output/results`. A run directory is named `<UTC datetime>-<run name>`, with a numeric suffix if needed.

The kubeconfig file is never copied. Its path is recorded locally in `resolved-config.json`; remove or redact that field before sharing if the path is sensitive.
