# Prototype measurement scripts (supplementary to impl.md Appendix A)

Read-only scratch scripts used to ground pr-945546e's spec in real data. They are not product code and are not run by pm. They only read git objects and refs; they never touch a PR workdir.

Setup used for Appendix A (in a disposable clone, not a PR workdir):

```
# fetch every open PR's branch head into private refs refs/scan/<pr-id>
git fetch --no-tags origin '+refs/heads/pm/pr-XXXXXXX-…:refs/scan/pr-XXXXXXX' …
# active_remote.txt: one line per PR: "<branch> <pr-id> <status> <plan> <sha>"
```

- `scan_overlap.py <dir-with-active_remote.txt>` — per-PR facts against `origin/master` (merge-base, contained, behind, changed paths) and file-level pair overlap; writes `scan.json`.
- `proto_interactions.py <dir> pr-a,pr-b,…` — `-U0` hunk intersection from each pair's merge-base, and Python changed-definition / new-reference matching with `ast` (code is parsed, never imported); writes `proto.json`.
- `registry_equiv.py <ref-a> <ref-b>` — splits `pm/project.yaml` into entries by line scanning (no YAML load) and reports entries changed by one, both, identically or differently since the pair's merge-base.

Set `REPO=<path to the clone>` (default: current directory).
