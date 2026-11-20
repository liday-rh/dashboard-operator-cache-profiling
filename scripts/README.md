# Scripts

## Cluster population

`populate-rhoai-scale-cluster.py` streams generated objects to one `oc apply` process. It waits for API acceptance only; it does not wait for Deployments or Pods.

### Requirements

- Python 3
- `oc` in `PATH`
- An active login with permission to create namespaces and namespaced resources
- A disposable test cluster

Confirm the target before running:

```sh
oc whoami
oc whoami --show-server
```

### Namespace-scale fixture

Creates 350 namespaces and nine lightweight resources per namespace. Deployments stay at zero replicas.

```sh
python3 scripts/populate-rhoai-scale-cluster.py \
  --namespaces 350 \
  --prefix rhoai-scale \
  --populate-resources \
  --deployment-replicas 0
```

### ConfigMap-payload fixture

Creates 90 namespaces with two 800 KiB ConfigMaps each, approximately 140.6 MiB of ConfigMap data in total.

```sh
python3 scripts/populate-rhoai-scale-cluster.py \
  --namespaces 90 \
  --prefix rhoai-payload \
  --populate-resources \
  --configmaps-per-namespace 2 \
  --configmap-payload-kib 800 \
  --deployment-replicas 0
```

### Namespace-only fixture

```sh
python3 scripts/populate-rhoai-scale-cluster.py \
  --namespaces 350 \
  --prefix rhoai-namespaces
```

### Dry run

Writes generated JSON documents to stdout without calling `oc`:

```sh
python3 scripts/populate-rhoai-scale-cluster.py \
  --namespaces 2 \
  --populate-resources \
  --dry-run
```

### Key options

| Option | Purpose |
|---|---|
| `--namespaces COUNT` | Required namespace count |
| `--populate-resources` | Add the workbench-like resource bundle |
| `--prefix NAME` | Namespace prefix and fixture label |
| `--deployment-replicas COUNT` | Deployment replicas; default `0` |
| `--configmaps-per-namespace COUNT` | ConfigMaps per populated namespace; default `1` |
| `--configmap-payload-kib KIB` | Payload per ConfigMap; range `0–900` KiB |
| `--allow-existing-namespaces` | Permit idempotent apply into existing target namespaces |
| `--dry-run` | Generate manifests without cluster changes |
| `--verbose-oc` | Show `oc apply` output |

The populated bundle contains a ServiceAccount, ConfigMap(s), Secret, zero-replica Deployment, Service, NetworkPolicy, PodDisruptionBudget, Role, and RoleBinding.

### Cleanup

Inspect the exact target first:

```sh
oc get namespaces -l scale.opendatahub.io/fixture=rhoai-scale
```

Delete only that fixture:

```sh
oc delete namespaces -l scale.opendatahub.io/fixture=rhoai-scale
```

Cleanup is destructive. Never use a broad or unverified selector.

## Benchmark collection

Requirements: `oc`, `jq`, an active login, and a running dashboard-operator pod.

```sh
scripts/collect-dashboard-cache-benchmark.sh \
  /path/to/kubeconfig \
  outputs/samples.tsv \
  20 \
  30 \
  expected-image-reference
```

Arguments are kubeconfig, output TSV, sample count, interval seconds, and exact expected image. The collector fails if the pod changes or the image does not match.

## Heap collection

The target image must expose pprof on `127.0.0.1:6060`. Set `PPROF_BIN` when `pprof` is not in `PATH`.

```sh
PPROF_BIN=/path/to/pprof \
scripts/collect-dashboard-heap-profile.sh \
  /path/to/kubeconfig \
  redhat-ods-applications \
  dashboard-operator-pod-name \
  outputs/profile-prefix
```

The script saves the forced-GC heap, debug text, and top reports for in-use and allocated bytes/objects.

## Chart rendering

`render-cache-comparison.py` requires Pillow and reads the recorded namespace benchmark TSV files from `outputs/`.

```sh
python3 scripts/render-cache-comparison.py
```
