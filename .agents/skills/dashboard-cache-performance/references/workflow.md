# Execution workflow

## 1. Configure and initialize

Copy `assets/run-config.example.json`, fill the cluster/source values, and adjust scenarios. Resolve a run directory:

```sh
python3 .agents/skills/dashboard-cache-performance/scripts/create_run.py run-config.json
```

Use the printed directory for every later command. Never reuse an earlier result directory.

## 2. Verify and snapshot the cluster

Before mutation:

- Run `oc whoami` and `oc whoami --show-server` with the configured kubeconfig.
- Confirm this is a dedicated/disposable cluster.
- Confirm nodes and ClusterOperators are healthy.
- Capture the dashboard-operator Deployment, owning lifecycle operator/CSV, Dashboard CR, DataScienceCluster, DSCI, pods, and current images under `<run>/cluster/before/`.
- Record how the dashboard-operator image and memory resources are managed. Do not assume direct Deployment patches will persist.

Stop if the target cluster, operator ownership path, or restoration path is unclear.

## 3. Prepare immutable images

For each resolved commit:

1. Create an isolated temporary Git worktree at the exact SHA.
2. Add the loopback-only pprof diagnostic change when retained profiles are required. Adapt the repository `patches/` examples to the target revision; never expose pprof through a Service, Route, or non-loopback bind.
3. Run the revision-appropriate unit tests and lint.
4. Build and push using the repository or cluster-supported build workflow.
5. Resolve the pushed image to an immutable digest.
6. Save build logs and provenance in the run directory.

If the user supplies images, verify their commit provenance. Never infer provenance from a mutable tag.

Record the digests:

```sh
python3 .agents/skills/dashboard-cache-performance/scripts/run_phase.py RUN_DIR \
  set-image --variant pre --image IMAGE_AT_SHA256

python3 .agents/skills/dashboard-cache-performance/scripts/run_phase.py RUN_DIR \
  set-image --variant post --image IMAGE_AT_SHA256
```

## 4. Run each workload

Run scenarios sequentially so their loads do not overlap.

Populate by calling the project resource generator through the skill wrapper:

```sh
python3 .agents/skills/dashboard-cache-performance/scripts/run_phase.py RUN_DIR \
  populate --scenario SCENARIO_NAME
```

The wrapper saves the command and exact labelled-object inventory. Confirm the counts before benchmarking.

Use `--dry-run` to save the generated manifest without changing the cluster.

### Pre-commit

1. Deploy the pre image through the cluster's owning configuration path.
2. Set the production memory limit and perform a cold operator start.
3. Record OOM/restart behavior. If it cannot survive, capture the failure, then apply the configured pre-profile limit and restart so collection can complete.
4. Wait for readiness, cache synchronization, and at least the configured stabilization period.
5. Record the observation:

```sh
python3 .agents/skills/dashboard-cache-performance/scripts/run_phase.py RUN_DIR \
  record-observation --scenario SCENARIO_NAME --variant pre \
  --memory-limit 1Gi --production-limit-result OOMKilled --oom-seconds 18
```

6. Collect:

```sh
PPROF_BIN=/path/to/pprof \
python3 .agents/skills/dashboard-cache-performance/scripts/run_phase.py RUN_DIR \
  collect --scenario SCENARIO_NAME --variant pre
```

### Post-commit

1. Deploy the post image through the same ownership path.
2. Restore the production memory limit and perform a cold operator start.
3. Wait for readiness, cache synchronization, and stabilization.
4. Record the production-limit result.
5. Run the same collection command with `--variant post`.

Do not change workload configuration, sampling, or collection commands between variants.

### Cleanup between workloads

Read `resolved_prefix` from `resolved-config.json`, inspect the matching namespaces, then pass that exact value:

```sh
python3 .agents/skills/dashboard-cache-performance/scripts/run_phase.py RUN_DIR \
  cleanup --scenario SCENARIO_NAME --confirm-prefix EXACT_RESOLVED_PREFIX
```

Cleanup is destructive. Do not use a shortened prefix, glob, or unverified selector.

## 5. Restore and verify

Restore the original image, resources, lifecycle configuration, and component state from the snapshot. Verify:

- Dashboard operator Ready with zero unexpected restarts.
- Dashboard Ready and route healthy.
- Nodes Ready.
- No degraded/unavailable ClusterOperators.

Save the final checks to `<run>/cluster/after/health.json`. Do not mark restoration complete without evidence.

## 6. Render and validate

```sh
python3 .agents/skills/dashboard-cache-performance/scripts/render_results.py RUN_DIR
```

Open the generated Markdown and charts. Confirm all relative links resolve and that summary calculations match the TSV data. Missing evidence must remain visibly marked rather than inferred.
