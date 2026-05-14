---
pr: pr-6be8ee6
workdir: /tmp/somewhere-unrelated
captured_at: 2026-05-14
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
env -u PYTHONPATH /home/pm/.local/bin/pm which
env -u PYTHONPATH /home/pm/.local/bin/pm qa docs
```

## What this demonstrates

`pm` was installed non-editable into `~/.local/share/pm/venv` (via `pip
install --force-reinstall --no-deps /workspace`, since `install.sh
--local` does an editable install — see Notes). `pm which` resolves to
the site-packages copy of `pm_core`, confirming the source tree is not
in play. `pm qa docs` is then run from `/tmp/somewhere-unrelated` (no
`pm/` directory present) with `PYTHONPATH` unset: stdout is the full
354-line packaged `qa_library.md` reference (first heading `# pm QA
library`), the exit code is 0, and stderr is empty.

## Notes

`install.sh --local` runs `pip install -e .`, which leaves the install
linked to the source tree and does not exercise `package-data` copy.
To validate the scenario's premise (a true non-editable install copying
packaged data into site-packages), this capture used `pip install
--force-reinstall --no-deps /workspace` directly against the same venv.
Result confirmed: site-packages contains `pm_core/docs/qa_library.md`
and `pm qa docs` succeeds from any cwd.

## Files

- `recording.cast` — asciinema replay of `pm which` and `pm qa docs` from `/tmp/somewhere-unrelated`
- `transcript.log` — plain-text dump of the cast (load-bearing artifact for grep/diff)
