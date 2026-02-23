# Test layout: complex dependency graph

Dummy plan for testing the Sugiyama tech tree layout algorithm.

12 PRs across 6 layers with multiple roots, fan-outs, fan-ins,
diamond patterns, and cross-tree dependencies.

```
Layer 0: tl01 (data model), tl02 (API client)
Layer 1: tl03 (auth, dep:01), tl04 (database, dep:01)
Layer 2: tl05 (ext API, dep:02+03), tl06 (cache, dep:02+04), tl07 (search, dep:04)
Layer 3: tl08 (user svc, dep:03+05), tl09 (content svc, dep:05+06+07), tl10 (notifications, dep:06)
Layer 4: tl11 (gateway, dep:08+09)
Layer 5: tl12 (integration tests, dep:10+11)
```
