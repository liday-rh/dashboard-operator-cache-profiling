# Dashboard cache optimization test plan

Issues: [RHOAIENG-98546](https://redhat.atlassian.net/browse/RHOAIENG-98546), parent epic [RHOAIENG-98537](https://redhat.atlassian.net/browse/RHOAIENG-98537), and original reproducer [RHOAIENG-96488](https://redhat.atlassian.net/browse/RHOAIENG-96488).

The goal is to prove the cache redesign before and after the optimization and lock the behavior in with tests so it does not regress. “Env tests” below means the requested envtest cache/event coverage.

## Acceptance criteria and closure gates

All three ticket acceptance criteria must be satisfied:

1. **Documented heap deltas before/after for both reproducers.**
   - Namespace-count reproducer: 300+ namespaces.
   - ConfigMap-payload reproducer: 90+ namespaces with 100–150 MiB of ConfigMap data.
   - Capture heap and RSS profiles and record retained types per GVK for both immutable versions in both scenarios.
2. **Green envtest cache-visibility suite.**
   - Assert which objects enter the cache.
   - Assert which object events enqueue reconciliation and which are filtered.
3. **Scale test passes within the default 256 MiB limit.**
   - Add a repeatable scale test.
   - Do not assert RSS in unit or envtest tests.
   - Keep the temporary 1 GiB workaround until the default-256 MiB scale test passes, then remove it.

Current assessment: criterion 1 is complete for both required reproducers, including immutable pre/post aggregate measurements and forced-GC retained-type/GVK profiles. Existing cache visibility envtests and both live 256 MiB optimized scale runs are green, but explicit event-enqueue coverage and repository-integrated scale automation still need to be confirmed or added to complete criteria 2 and 3.

## 1. Establish the before/after boundary

Use immutable source and image digests:

- Pre-optimization: source `466ab8c88cd769b3001660e569b52e1c7c1cc0f3`; image `quay.io/opendatahub/odh-dashboard-operator@sha256:a951516f4f848952bc15ccef939e93f525ad06bf12f9729f50e14192290627dc`. Its dashboard-operator tree was verified equivalent to the actual pre-PR #10250 boundary.
- Post-optimization: source `27efc6479a9cc1b503f7afa25905620933c338bc`; image `quay.io/opendatahub/odh-dashboard-operator@sha256:8b8a0036cf8ca2c52e53ce3078d26f2683c843bb58af6542e4f02cae94622766`, after the final metadata-cache change in PR #10458.
- The post image contains PRs #10250, #10324, #10327, #10356, and #10458: ConfigMap/Secret cache removal, scoped caches, strict informer registration/APIReader, scoped OdhDashboardConfig watch, and metadata-only watches.
- Use the same Go toolchain and an identical profiling-only patch exposing `pprof` without a Service or Route when retained heap evidence cannot be obtained from the released images.
- Record image digests, OpenShift/RHOAI versions, node sizing, object counts, operator Deployment specification, and test-generator revision.

Keep the operator at the temporary 1 GiB limit only where the pre-change binary needs it to survive long enough to capture useful profiles. The production-limit behavior must still be attempted and recorded.

Status: immutable boundaries are verified. Source-equivalent diagnostic builds were validated with full unit and lint suites and used only for loopback pprof collection.

## 2. Profile on a dedicated large cluster

Use a clean, dedicated cluster and alternate the two images against identical workload states.

| Scenario | Required workload | Purpose |
|---|---|---|
| Control | Cluster before synthetic load | Establish platform/operator baseline |
| Namespace reproducer | 350 synthetic namespaces, ensuring well over 300 total | Required namespace-count reproducer |
| Payload reproducer | At least 90 namespaces with a combined 100–150 MiB of ConfigMap data | Required ConfigMap-payload reproducer |
| Combined worst case | 350 namespaces plus approximately 140 MiB of ConfigMap data | Additional stress coverage, not a substitute for either required reproducer |

For the namespace scenario, ramp through 100, 200, 300, and 350 namespaces where practical. This produces a memory-growth slope rather than only two endpoints.

For the payload scenario, use a separate fixture. One supported configuration is 90 namespaces, two ConfigMaps per namespace, and an 800 KiB payload per ConfigMap, producing approximately 140.6 MiB of payload:

```sh
python3 scripts/populate-rhoai-scale-cluster.py \
  --namespaces 90 \
  --prefix rhoai-payload \
  --populate-resources \
  --configmaps-per-namespace 2 \
  --configmap-payload-kib 800
```

Verify the actual serialized payload and object counts before profiling. Do not combine the payload and namespace-count results when demonstrating the two acceptance-criterion reproducers.

For every image and required scenario:

- Perform at least three cold operator starts where cluster time permits.
- Wait for cache sync and a stable memory plateau; target at least 30 minutes of steady-state collection for final acceptance evidence.
- Capture:

  - Container RSS and working set.
  - `process_resident_memory_bytes`.
  - Go heap allocation/in-use bytes, object counts, GC frequency, and GC pauses.
  - Forced-GC heap profiles using `/debug/pprof/heap?gc=1`.
  - Peak startup and steady-state memory.
  - Restarts, OOM events, reconcile rate, and operator logs.

- Produce `inuse_space` and `inuse_objects` reports. Map concrete Kubernetes types back to GVKs so the report shows retained bytes/objects for ConfigMap, Secret, Deployment, ServiceAccount, RoleBinding, HTTPRoute, ConsoleLink, and related informer/store allocations.
- Preserve raw profiles and a comparison table containing absolute and percentage deltas.

Success is not merely “lower memory”: unrelated namespace/object growth should have a near-flat optimized slope, and the optimized result must show safe headroom below 256 MiB.

Status:

- Namespace reproducer: pre/post comparison completed at 350 namespaces / 3,500 objects. The pre image OOMed after 18 seconds at 256 MiB; the post image completed the sampling window with zero restarts and a 39 MiB median working set. Forced-GC retained heap fell from 138.68 MiB to 10.54 MiB (92.4%).
- Payload reproducer: pre/post comparison completed at 90 namespaces / 990 objects / 140.65 MiB of ConfigMap data. The pre image OOMed after 27 seconds at 256 MiB; the post image completed the sampling window with zero restarts and a 36 MiB median working set. Forced-GC retained heap fell from 204.78 MiB to 6.61 MiB (96.8%).
- Retained types per GVK: captured for both required reproducers. Pre profiles are dominated by full ConfigMap/Secret and workload-object decode paths; those paths are absent from the corresponding optimized profiles.

## 3. Add focused envtest coverage

Extend the existing cache integration suite, exercising the production `SetupWithManager` path instead of manually registering informers.

Add or confirm two explicit matrices:

- Cache visibility:

  - Correctly labelled/in-scope objects enter the cache.
  - Unlabelled and wrong-namespace objects do not.
  - ConfigMaps and Secrets remain uncached but visible through `APIReader`.
  - An `APIReader` access does not create an informer.
  - ServiceAccount and ConsoleLink are metadata-only.
  - The OdhDashboardConfig watch sees only its exact namespace/name.
  - Optional API absence remains non-fatal.

- Event-to-reconcile behavior:

  - Selected create/update/delete events enqueue the singleton Dashboard.
  - Filtered objects do not enqueue it.
  - Pure status churn is filtered only for types where intended.
  - Deployment and HTTPRoute status changes still enqueue when availability depends on them.
  - Named and labelled ConfigMap events still trigger reconciliation.

Use a recording reconciler around the production watch registration and `Eventually`/`Consistently` assertions—no sleeps, RSS checks, or duplicated test-only cache configuration.

Run the complete post-optimization unit and envtest suites:

```sh
make test
make test-integration
```

Record the exact revision, test names, commands, and CI/local results.

Status: the existing cache-visibility suite passed in CI at `27efc647`. Audit the event-to-reconcile matrix and add any missing cases before declaring the complete technical implementation finished.

## 4. Add the repeatable live scale test

Add an opt-in, build-tagged scenario to `dashboard-operator/test/e2e`, using the Kubernetes client because the E2E image intentionally contains no `oc`.

The test should:

- Require an explicit destructive-scale opt-in.
- Support both required workload modes: 350 generated namespaces and at least 90 namespaces with approximately 140 MiB of ConfigMaps.
- Label every generated resource with a unique run ID.
- Refuse to operate on protected or existing namespaces.
- Use bounded creation concurrency and verified cleanup.
- Preflight that the actual manager memory limit is exactly 256 MiB.
- Restart the operator after load creation to exercise cold cache population.
- Require the operator and Dashboard to remain Ready for at least 30 minutes with zero OOMKills and zero container restarts.
- Verify a controlled managed-resource drift is repaired.
- Save memory metrics, events, logs, workload inventory, and JUnit results as artifacts.

The cgroup's 256 MiB limit is the hard automated gate; RSS and heap remain diagnostic artifacts rather than unit-test assertions.

Status: the local fixture generator is repeatable, and the optimized image passed the 350-namespace live test at 256 MiB. Repository-integrated, opt-in scale automation covering both workload modes remains outstanding.

## 5. Sign-off and remove the workaround

Only after the optimized image passes the repeatable 256 MiB scale test:

- Remove the 1 GiB override from the validation/release configuration.
- Verify the rendered/default manifest and live Deployment both use 256 MiB.
- Rerun both required scale scenarios at the default limit.
- Run unit, envtest/integration, E2E scale, lint, and build validation.
- Attach the raw-profile location, summarized deltas for both reproducers, retained-GVK reports, exact image digests, workload manifests, and scale-test results to RHOAIENG-98546.

The ticket can be closed only when both before/after reproducer reports are complete, the cache/event envtest suite is green, the repeatable scale test passes at 256 MiB, and the temporary 1 GiB workaround is confirmed removed.
