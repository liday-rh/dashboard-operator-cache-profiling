# Result contract

Every completed run directory contains:

```text
<run-id>/
├── resolved-config.json
├── dashboard-cache-testing-summary.md
├── charts/
│   ├── cache-summary-comparison.svg
│   └── cache-working-set-series.svg
├── cluster/
│   └── before/
└── scenarios/
    └── <scenario>/
        ├── inventory.json
        ├── population.json
        ├── pre/
        │   ├── samples.tsv
        │   ├── environment.json
        │   ├── observation.json
        │   ├── heap-heap.pb.gz
        │   ├── heap-inuse-space.txt
        │   └── heap-inuse-objects.txt
        └── post/
            └── ...
```

The summary preserves this section order:

1. Summary and result table
2. Memory comparison chart
3. Working-set timeline
4. Detailed section for each workload
5. Retained-type analysis
6. Method
7. Evidence links
8. Status

Do not invent missing OOM timing, limits, profile totals, or health results. Render missing evidence as `Not recorded` and identify it in Status.
