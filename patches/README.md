# Diagnostic profiling patches

These patches add a loopback-only pprof endpoint and rebuild only the manager binary on top of the corresponding released image.

| Patch | Source revision |
|---|---|
| `pre-optimization-pprof.patch` | `466ab8c88cd769b3001660e569b52e1c7c1cc0f3` |
| `post-optimization-pprof.patch` | `27efc6479a9cc1b503f7afa25905620933c338bc` |

Apply from the root of a matching `odh-dashboard` checkout:

```sh
git apply --check /path/to/pre-optimization-pprof.patch
git apply /path/to/pre-optimization-pprof.patch
```

The endpoint binds to `127.0.0.1:6060`. The patches add no Service, Route, container port, or RBAC. They are diagnostic artifacts, not production changes.
