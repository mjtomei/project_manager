# Example persisted notes, history, settings and brief state (pr-2588ead)

Supplements [`../impl.md`](../impl.md). If anything here disagrees with
section 1 or section 4 of the spec, the spec is right and this file is wrong.

**Data provenance.** There are three projects:

- **project-manager** (key `828c8d0a`, the real `repo_id[:8]`) uses real PR
  ids, titles and numbers. Its four merges are the real merges on `master` on
  2026-11-01 (#272, #280, #267, #282), as the hub's synced registry would
  record them.
- **cosmic_ac** (key `5e1c0a77`) is an **illustrative fixture** standing in for
  the D5 adoption project. None of its data was read from the real cosmic_ac.
- **omerta-core** (key `0e7a2b19`) is an **illustrative fixture** standing in
  for a D8 child project. It is used for the unavailable-project cases.

All times after 2026-11-01 are illustrative. The owner's zone is
`America/Chicago` (CST, UTC−6, after 2026-11-01).

---

## 1. After setup (Sun 1 Nov 2026, ~14:41 CST)

The setup conversation is in [`conversations.md`](conversations.md) §1.

### 1.1 `project-manager/pm/notes.txt` (hub project)

The file before setup had only the QA note under `## QA`. Setup changed only
the new `## Owner Brief` section; the other sections are byte-identical.

```text
## General

## Implementation

## Review

## QA

If you need to use the pm tool and are running in a container where it isn't availble, use ./install.sh --local from the pm repo directory.

## Merge

## Watcher

## Owner Brief

### Whole brief
- Lead with anything that needs me; I read this on my phone before standup. [owner 2026-11-01]
- Keep the whole brief to about 25 lines. [owner 2026-11-01]
- Order projects by what needs me; on ties, project-manager first. [owner 2026-11-01]

### This project
- Collapse PRs with no activity for a week into one count line; don't list them. [owner 2026-11-01]
- For each merge, name its plan. [owner 2026-11-01]
```

### 1.2 `cosmic_ac/pm/notes.txt` (fixture)

```text
## General

## Implementation

## Review

## QA

## Merge

## Watcher

## Owner Brief

### This project
- List every merge on its own line with its one-line impact; this project merges rarely. [owner 2026-11-01]
```

The setup agent wrote nothing to omerta-core: its pm root could not be read
(`project.yaml not found`), and the owner gave no preference for it.

### 1.3 Revision journals (`<project>/pm/notes-journal.jsonl`)

`project-manager/pm/notes-journal.jsonl` (each record is one JSON line; shown
wrapped here):

```json
{"rev": "r-20261101T2041Z-1a2b", "section": "Owner Brief", "block": "Whole brief",
 "project": "project-manager", "at": "2026-11-01T20:41:12Z", "authority": "owner-confirmed",
 "before_sha": "e3b0c442", "after_sha": "7d41a9c0",
 "after_text": "- Lead with anything that needs me; I read this on my phone before standup. [owner 2026-11-01]\n- Keep the whole brief to about 25 lines. [owner 2026-11-01]\n- Order projects by what needs me; on ties, project-manager first. [owner 2026-11-01]",
 "quote": "Lead with what needs me, I read it on my phone before standup. Keep it to about 25 lines. project-manager first when it's a tie.",
 "summary": "initial whole-brief guidance from setup", "session": "brief:setup:owner (claude 6f0c…)"}
{"rev": "r-20261101T2041Z-2c3d", "section": "Owner Brief", "block": "This project",
 "project": "project-manager", "at": "2026-11-01T20:41:30Z", "authority": "owner-confirmed",
 "before_sha": "e3b0c442", "after_sha": "c19e2f77",
 "after_text": "- Collapse PRs with no activity for a week into one count line; don't list them. [owner 2026-11-01]\n- For each merge, name its plan. [owner 2026-11-01]",
 "quote": "Don't list the old stale PRs, just count them. Tell me which plan a merge belongs to.",
 "summary": "initial project-manager guidance from setup", "session": "brief:setup:owner (claude 6f0c…)"}
```

`cosmic_ac/pm/notes-journal.jsonl`:

```json
{"rev": "r-20261101T2042Z-3e4f", "section": "Owner Brief", "block": "This project",
 "project": "cosmic_ac", "at": "2026-11-01T20:42:05Z", "authority": "owner-confirmed",
 "before_sha": "e3b0c442", "after_sha": "5b2e81d4",
 "after_text": "- List every merge on its own line with its one-line impact; this project merges rarely. [owner 2026-11-01]",
 "quote": "cosmic merges rarely, so show each one.",
 "summary": "initial cosmic_ac guidance from setup", "session": "brief:setup:owner (claude 6f0c…)"}
```

### 1.4 Brief settings: `~/.pm/briefs/owner/config.json`

```json
{
  "schema": "pm.brief.config/1",
  "name": "owner",
  "hub": {"pm_root": "/home/matt/claude-work/project-manager/pm",
          "session_tag": "project_manager-c5a1006b"},
  "projects": [
    {"key": "828c8d0a", "pm_root": "/home/matt/claude-work/project-manager/pm", "label": "project-manager"},
    {"key": "5e1c0a77", "pm_root": "/home/matt/claude-work/cosmic_ac/pm", "label": "cosmic_ac"},
    {"key": "0e7a2b19", "pm_root": "/home/matt/claude-work/omerta/core/pm", "label": "omerta-core"}
  ],
  "cadence": {"spec": "weekdays 08:30", "tz": "America/Chicago"},
  "destinations": [{"kind": "local"}],
  "schedule": "active",
  "created_at": "2026-11-01T20:39:50Z",
  "updated_at": "2026-11-01T20:44:31Z"
}
```

`~/.pm/briefs/owner/config-journal.jsonl`. Settings commands record a quote only where one is required, i.e. `start`, `pause`, `resume` and `stop`:

```json
{"at": "2026-11-01T20:39:50Z", "change": "create (schedule off)", "quote": "", "session": "brief:setup:owner"}
{"at": "2026-11-01T20:40:02Z", "change": "projects add project-manager, cosmic_ac, omerta-core", "quote": "", "session": "brief:setup:owner"}
{"at": "2026-11-01T20:40:10Z", "change": "cadence weekdays 08:30 America/Chicago", "quote": "", "session": "brief:setup:owner"}
{"at": "2026-11-01T20:44:31Z", "change": "schedule off -> active", "quote": "Looks good, start it.", "session": "brief:setup:owner"}
```

### 1.5 `pm brief guidance show --name owner` (after setup)

```text
Effective owner-brief guidance — brief "owner" (hub: project-manager)

Whole brief  ·  project-manager/pm/notes.txt § Owner Brief › Whole brief
  rev r-20261101T2041Z-1a2b · owner-confirmed 2026-11-01 · sha 7d41a9c0
  - Lead with anything that needs me; I read this on my phone before standup. [owner 2026-11-01]
  - Keep the whole brief to about 25 lines. [owner 2026-11-01]
  - Order projects by what needs me; on ties, project-manager first. [owner 2026-11-01]

project-manager  ·  project-manager/pm/notes.txt § Owner Brief › This project
  rev r-20261101T2041Z-2c3d · owner-confirmed 2026-11-01 · sha c19e2f77
  - Collapse PRs with no activity for a week into one count line; don't list them. [owner 2026-11-01]
  - For each merge, name its plan. [owner 2026-11-01]

cosmic_ac  ·  cosmic_ac/pm/notes.txt § Owner Brief › This project
  rev r-20261101T2042Z-3e4f · owner-confirmed 2026-11-01 · sha 5b2e81d4
  - List every merge on its own line with its one-line impact; this project merges rarely. [owner 2026-11-01]

omerta-core  ·  notes unreadable: project.yaml not found at /home/matt/claude-work/omerta/core/pm
  (no guidance)

Settings (brief config, not notes)
  weekdays 08:30 America/Chicago · destination: local dashboard (project-manager) · schedule: active
  next brief: Mon 2 Nov 2026 08:30 CST

Always included, whatever the guidance says
  waiting on you · blockers and failures · every merge, with how it merged · projects not refreshed ·
  registry data problems · guidance changes · as-of time, interval, links

Notes changes are written to each project's checkout and are not committed automatically.
```

---

## 2. After the first feedback (Mon 2 Nov 2026, ~09:15 CST)

The conversation is in [`conversations.md`](conversations.md) §2. Two blocks
changed. project-manager's `### This project` block and every other section are
unchanged.

### 2.1 project-manager `### Whole brief`: before → after

```diff
 ### Whole brief
-- Lead with anything that needs me; I read this on my phone before standup. [owner 2026-11-01]
-- Keep the whole brief to about 25 lines. [owner 2026-11-01]
+- Start with one "Needs you" list across all projects, oldest first, then the projects. [owner 2026-11-02]
+- Keep the whole brief to about 15 lines. [owner 2026-11-02]
+- Batch each project's merges into one line. [owner 2026-11-02]
+- Keep notices about projects that could not be refreshed to one short line each. [owner 2026-11-02]
 - Order projects by what needs me; on ties, project-manager first. [owner 2026-11-01]
```

### 2.2 cosmic_ac `### This project`: before → after

The whole-brief "batch merges" line conflicts with cosmic_ac's own "list every
merge" line. The owner chose to keep cosmic_ac's exception, so that line stays.
Under the precedence rule (impl §6.4) the project block wins for its own lines.

```diff
 ### This project
 - List every merge on its own line with its one-line impact; this project merges rarely. [owner 2026-11-01]
+- Leave out PRs whose title starts with "Notebook:" unless they are blocked or waiting on me. [owner 2026-11-02]
```

### 2.3 Journal records appended

```json
{"rev": "r-20261102T1514Z-5a6b", "section": "Owner Brief", "block": "Whole brief",
 "project": "project-manager", "at": "2026-11-02T15:14:40Z", "authority": "owner-confirmed",
 "before_sha": "7d41a9c0", "after_sha": "a8f3d215",
 "after_text": "- Start with one \"Needs you\" list across all projects, oldest first, then the projects. [owner 2026-11-02]\n- Keep the whole brief to about 15 lines. [owner 2026-11-02]\n- Batch each project's merges into one line. [owner 2026-11-02]\n- Keep notices about projects that could not be refreshed to one short line each. [owner 2026-11-02]\n- Order projects by what needs me; on ties, project-manager first. [owner 2026-11-01]",
 "quote": "Too long, and I had to scroll for the things I need to do. Put everything that needs me in one list at the very top across all projects. Batch merges into one line per project. … 15 is fine. … Yes, one line for omerta is fine.",
 "summary": "top Needs-you list; ~15 lines; batch merges; one-line unrefreshed notices",
 "session": "brief:feedback:owner (claude 91ad…)"}
```

```json
{"rev": "r-20261102T1515Z-7c8d", "section": "Owner Brief", "block": "This project",
 "project": "cosmic_ac", "at": "2026-11-02T15:15:02Z", "authority": "owner-confirmed",
 "before_sha": "5b2e81d4", "after_sha": "0c6e93aa",
 "after_text": "- List every merge on its own line with its one-line impact; this project merges rarely. [owner 2026-11-01]\n- Leave out PRs whose title starts with \"Notebook:\" unless they are blocked or waiting on me. [owner 2026-11-02]",
 "quote": "For cosmic_ac, skip notebook PRs unless they're stuck or waiting on me. … Yes, the ones titled Notebook:. Keep listing cosmic merges one by one.",
 "summary": "cosmic_ac: omit Notebook: PRs unless blocked/waiting; keep per-merge lines",
 "session": "brief:feedback:owner (claude 91ad…)"}
```

Nothing was recorded for the owner's request that "cosmic_ac doc-only PRs can
just merge without me". That is merge authority, not brief guidance. See
[`conversations.md`](conversations.md) §2.

---

## 3. A direct edit (Tue 3 Nov 2026, 07:10 CST)

The owner opened `pm notes` and added one line by hand to project-manager's
`### This project` block. pm records nothing at edit time. Brief collection is
read-only, so it does not write the journal.

```text
### This project
- Collapse PRs with no activity for a week into one count line; don't list them. [owner 2026-11-01]
- For each merge, name its plan. [owner 2026-11-01]
- Mention when a PR touching containers merges.
```

`pm brief guidance show` now flags the block:

```text
project-manager  ·  project-manager/pm/notes.txt § Owner Brief › This project
  rev r-20261101T2041Z-2c3d + DIRECT EDIT (file differs from history; sha 4e7710b9)
  - Collapse PRs with no activity for a week into one count line; don't list them. [owner 2026-11-01]
  - For each merge, name its plan. [owner 2026-11-01]
  - Mention when a PR touching containers merges.   ← direct edit, honoured as the owner's
```

The next brief lists it as a required `guidance_change` item,
`guidance:direct:828c8d0a:This project:4e7710b9`. The composer records that it
cannot follow the new line yet: the brief input carries no file or area
information, which #286's decision records may add later. The next
`guidance apply` or `rollback` on *this block* first appends the record
below. No change to this block happens in these examples (the 9 Nov rollback
is on the `Whole brief` block), so through §B6 the edit is honoured but not
yet in the history:

```json
{"rev": "r-<time of the next change to this block>", "section": "Owner Brief", "block": "This project",
 "project": "project-manager", "at": "<time of that change>", "authority": "direct-edit",
 "before_sha": "c19e2f77", "after_sha": "4e7710b9",
 "after_text": "- Collapse PRs with no activity for a week into one count line; don't list them. [owner 2026-11-01]\n- For each merge, name its plan. [owner 2026-11-01]\n- Mention when a PR touching containers merges.",
 "quote": "", "summary": "edit made directly in notes.txt (not via pm brief); recorded before the next change",
 "session": "detected by guidance apply"}
```

## 4. Rollback (Mon 9 Nov 2026, 09:31 CST)

The owner asked to undo the 2 Nov whole-brief change ([`conversations.md`](conversations.md) §3).
Rollback appends a new revision; it never rewrites history:

```json
{"rev": "r-20261109T1531Z-f3a4", "section": "Owner Brief", "block": "Whole brief",
 "project": "project-manager", "at": "2026-11-09T15:31:20Z", "authority": "rollback",
 "rollback_of": "r-20261102T1514Z-5a6b", "restores": "r-20261101T2041Z-1a2b",
 "before_sha": "a8f3d215", "after_sha": "7d41a9c0",
 "after_text": "- Lead with anything that needs me; I read this on my phone before standup. [owner 2026-11-01]\n- Keep the whole brief to about 25 lines. [owner 2026-11-01]\n- Order projects by what needs me; on ties, project-manager first. [owner 2026-11-01]",
 "quote": "Undo last week's change to the whole brief, the top list is noisy.",
 "summary": "rollback whole brief to the setup version", "session": "brief:feedback:owner (claude 2b7e…)"}
```

---

## 5. Brief state: `~/.pm/briefs/owner/state.json`

### 5.1 After the first published brief (Mon 2 Nov, run `20261102T143000Z-4f1a`)

This is an excerpt: snapshots are shortened to the PRs these examples mention,
and the real snapshot holds every PR in each project.

```json
{
  "schema": "pm.brief.state/1",
  "boundary": {"as_of": "2026-11-02T14:30:00Z", "run_id": "20261102T143000Z-4f1a",
               "published_at": "2026-11-02T14:32:48Z"},
  "snapshot": {
    "828c8d0a": {"observed_at": "2026-11-02T14:30:02Z", "prs": {
      "pr-62ad13d": {"status": "merged", "merged_at": "2026-11-01T14:49:10Z"},
      "pr-574e851": {"status": "merged", "merged_at": "2026-11-01T15:07:17Z"},
      "pr-049649a": {"status": "merged", "merged_at": "2026-11-01T15:18:34Z"},
      "pr-e076433": {"status": "merged", "merged_at": "2026-11-01T17:26:36Z"},
      "pr-2588ead": {"status": "in_progress", "updated_at": "2026-11-01T20:08:03Z"}}},
    "5e1c0a77": {"observed_at": "2026-11-02T14:30:03Z", "prs": {
      "pr-c41a2b0": {"status": "merged"}, "pr-c44d9e1": {"status": "merged"},
      "pr-c45f310": {"status": "qa"},
      "pr-c46b7a2": {"status": "sign_off", "signoff": "SIGNOFF_MERGE", "fresh": true},
      "pr-c47e5d4": {"status": "in_review"},
      "pr-c48a6c9": {"status": "in_review"}}}
  },
  "events_published": {
    "merge:828c8d0a:pr-62ad13d": "2026-11-02T14:32:48Z",
    "merge:828c8d0a:pr-574e851": "2026-11-02T14:32:48Z",
    "merge:828c8d0a:pr-049649a": "2026-11-02T14:32:48Z",
    "merge:828c8d0a:pr-e076433": "2026-11-02T14:32:48Z",
    "merge:5e1c0a77:pr-c41a2b0": "2026-11-02T14:32:48Z",
    "merge:5e1c0a77:pr-c44d9e1": "2026-11-02T14:32:48Z"
  },
  "open_items": {
    "wait:828c8d0a:pr-2588ead:spec-approval": {"first_seen": "2026-11-02T14:30:02Z",
      "since": "2026-11-01T20:07:49Z", "since_source": "spec_pending.requested_at", "fp": "b81f"},
    "wait:5e1c0a77:pr-c46b7a2:merge-approval": {"first_seen": "2026-11-02T14:30:03Z",
      "since": "2026-10-31T15:05:00Z", "since_source": "signoff.ts", "fp": "40ce"},
    "fail:5e1c0a77:pr-c47e5d4:review-launch": {"first_seen": "2026-11-02T14:30:03Z",
      "since": "2026-11-02T14:30:03Z", "since_source": "first_seen", "fp": "9a17"},
    "proj:0e7a2b19:unavailable": {"first_seen": "2026-11-02T14:30:01Z",
      "since": "2026-11-02T14:30:01Z", "since_source": "first_seen", "fp": "not-found"},
    "idle:828c8d0a:*": {"first_seen": "2026-11-02T14:30:02Z", "count": 42, "fp": "42"}
  },
  "guidance_shas": {"828c8d0a/Whole brief": "7d41a9c0", "828c8d0a/This project": "c19e2f77",
                    "5e1c0a77/This project": "5b2e81d4"},
  "in_flight": null,
  "last_failure": null,
  "retry": {"attempts": 0, "next_at": null},
  "project_refresh": {
    "828c8d0a": {"registry": "ok", "live": "ok", "last_ok": "2026-11-02T14:30:02Z"},
    "5e1c0a77": {"registry": "ok", "live": "ok", "last_ok": "2026-11-02T14:30:03Z"},
    "0e7a2b19": {"registry": "unavailable: project.yaml not found", "last_ok": null}
  }
}
```

### 5.2 Wed 4 Nov after the first failed delivery (08:31:52 CST)

The boundary is still Tuesday's, and `merge:5e1c0a77:pr-c50d8e2` is **not** in
`events_published`:

```json
{
  "boundary": {"as_of": "2026-11-03T14:30:00Z", "run_id": "20261103T143000Z-8b2c",
               "published_at": "2026-11-03T14:31:57Z"},
  "in_flight": null,
  "last_failure": {"run_id": "20261104T143000Z-c3d4", "at": "2026-11-04T14:31:52Z",
                   "stage": "deliver:local",
                   "error": "OSError: [Errno 28] No space left on device: '/home/matt/.pm/sessions/project_manager-c5a1006b/captures/briefs/owner/.20261104T143000Z-c3d4.html.tmp'"},
  "retry": {"attempts": 1, "next_at": "2026-11-04T14:36:52Z"}
}
```

### 5.3 Wed 4 Nov after the successful third attempt (08:53:10 CST)

```json
{
  "boundary": {"as_of": "2026-11-04T14:51:52Z", "run_id": "20261104T145152Z-0a1b",
               "published_at": "2026-11-04T14:53:10Z"},
  "events_published": {"…": "…", "merge:5e1c0a77:pr-c50d8e2": "2026-11-04T14:53:10Z",
                       "resolved:5e1c0a77:pr-c47e5d4:review-launch": "2026-11-04T14:53:10Z"},
  "last_failure": null,
  "retry": {"attempts": 0, "next_at": null},
  "delivery_history": [
    {"run_id": "20261104T143000Z-c3d4", "outcome": "failed", "at": "2026-11-04T14:31:52Z", "error": "No space left on device"},
    {"run_id": "20261104T143652Z-e5f6", "outcome": "failed", "at": "2026-11-04T14:38:20Z", "error": "No space left on device"},
    {"run_id": "20261104T145152Z-0a1b", "outcome": "published", "at": "2026-11-04T14:53:10Z"}
  ]
}
```

`delivery_history` keeps the last 20 attempts for `pm brief status` and for
the renderer's "Delivered on attempt …" footer.

### 5.4 Receipt: `runs/20261104T145152Z-0a1b/receipt.json`

```json
{"run_id": "20261104T145152Z-0a1b", "published_at": "2026-11-04T14:53:10Z",
 "composer": "draft", "draft_attempts": 1,
 "destinations": [{"kind": "local",
   "files": ["/home/matt/.pm/sessions/project_manager-c5a1006b/captures/briefs/owner/20261104T145152Z-0a1b.html",
             "/home/matt/.pm/sessions/project_manager-c5a1006b/captures/briefs/owner/20261104T145152Z-0a1b.md"],
   "latest_updated": true}],
 "next_state_sha": "1f9c0b44"}
```

---

## 6. Brief input for the first brief (run `20261102T143000Z-4f1a`)

`~/.pm/briefs/owner/runs/20261102T143000Z-4f1a/input.json`. Every item is shown;
the project-manager snapshot is abbreviated.

```json
{
  "schema": "pm.brief.input/1",
  "brief": "owner",
  "run_id": "20261102T143000Z-4f1a",
  "as_of": "2026-11-02T14:30:00Z",
  "interval": {"from": "2026-11-01T14:30:00Z", "to": "2026-11-02T14:30:00Z",
               "kind": "baseline", "scheduled_slots": 1, "skipped_while_paused": 0},
  "limits": {"max_lines": 40, "max_line_chars": 160},
  "projects": [
    {
      "key": "828c8d0a", "name": "project-manager", "pm_root": "/home/matt/claude-work/project-manager/pm",
      "repo": "https://github.com/mjtomei/project_manager.git",
      "refresh": {"registry": "ok", "live": "ok", "registry_synced": "2026-11-02T14:27:41Z"},
      "position": {"open": {"in_progress": 9, "in_review": 36, "qa": 7, "sign_off": 0, "pending": 391},
                   "plans_touched": [{"id": "bugs", "title": "bugs", "merged": 22, "total": 239},
                                     {"id": "improvements", "title": "improvements", "merged": 14, "total": 57}]},
      "next_action": {"item": "wait:828c8d0a:pr-2588ead:spec-approval", "text": "Review the spec for #287"},
      "items": [
        {"id": "wait:828c8d0a:pr-2588ead:spec-approval", "kind": "owner_decision", "observation": "waiting",
         "required": true, "change": "new", "since": "2026-11-01T20:07:49Z", "since_source": "spec_pending.requested_at",
         "age": "18h",
         "pr": {"id": "pr-2588ead", "display": "#287", "title": "Scheduled concise multi-project progress and change briefs",
                "gh_pr": "https://github.com/mjtomei/project_manager/pull/287", "plan": "watchers"},
         "facts": {"reason": "Owner requires grounded implementation spec and complete onboarding, feedback and brief-generation prompts with rendered examples before product implementation/review/QA."},
         "links": [{"label": "#287", "url": "https://github.com/mjtomei/project_manager/pull/287"},
                   {"label": "spec", "url": "https://github.com/mjtomei/project_manager/blob/pm/pr-2588ead-scheduled-concise-multi-project-progress-and-chang/pm/specs/pr-2588ead/impl.md"}]},
        {"id": "merge:828c8d0a:pr-62ad13d", "kind": "merged", "observation": "completed", "required": true, "change": "new",
         "since": "2026-11-01T14:49:10Z", "since_source": "merged_at",
         "pr": {"id": "pr-62ad13d", "display": "#272", "title": "Make PR close non-destructive: retain registry history, branches and workdir", "gh_pr": "https://github.com/mjtomei/project_manager/pull/272", "plan": "bugs"},
         "merge": {"mode": "unattributed", "via": null, "detail": "no merge_record (merged before provenance was recorded)"},
         "impact": "",
         "links": [{"label": "#272", "url": "https://github.com/mjtomei/project_manager/pull/272"},
                   {"label": "report", "url": "http://127.0.0.1:8765/pr-62ad13d/report.html"}]},
        {"id": "merge:828c8d0a:pr-574e851", "kind": "merged", "observation": "completed", "required": true, "change": "new",
         "since": "2026-11-01T15:07:17Z", "since_source": "merged_at",
         "pr": {"id": "pr-574e851", "display": "#280", "title": "Bug: never fall back to host execution when container mode is enabled", "gh_pr": "https://github.com/mjtomei/project_manager/pull/280", "plan": "bugs"},
         "merge": {"mode": "unattributed", "via": null, "detail": "no merge_record"}, "impact": "",
         "links": [{"label": "#280", "url": "https://github.com/mjtomei/project_manager/pull/280"},
                   {"label": "report", "url": "http://127.0.0.1:8765/pr-574e851/report.html"}]},
        {"id": "merge:828c8d0a:pr-049649a", "kind": "merged", "observation": "completed", "required": true, "change": "new",
         "since": "2026-11-01T15:18:34Z", "since_source": "merged_at",
         "pr": {"id": "pr-049649a", "display": "#267", "title": "Remove all-PR autostart and fail closed on malformed or targetless saved state", "gh_pr": "https://github.com/mjtomei/project_manager/pull/267", "plan": "bugs"},
         "merge": {"mode": "unattributed", "via": null, "detail": "no merge_record"}, "impact": "",
         "links": [{"label": "#267", "url": "https://github.com/mjtomei/project_manager/pull/267"},
                   {"label": "report", "url": "http://127.0.0.1:8765/pr-049649a/report.html"}]},
        {"id": "merge:828c8d0a:pr-e076433", "kind": "merged", "observation": "completed", "required": true, "change": "new",
         "since": "2026-11-01T17:26:36Z", "since_source": "merged_at",
         "pr": {"id": "pr-e076433", "display": "#282", "title": "Make model routing names and documentation role-neutral", "gh_pr": "https://github.com/mjtomei/project_manager/pull/282", "plan": "improvements"},
         "merge": {"mode": "unattributed", "via": null, "detail": "no merge_record"}, "impact": "",
         "links": [{"label": "#282", "url": "https://github.com/mjtomei/project_manager/pull/282"},
                   {"label": "report", "url": "http://127.0.0.1:8765/pr-e076433/report.html"}]},
        {"id": "idle:828c8d0a:*", "kind": "issue", "observation": "stale", "required": false, "change": "new",
         "facts": {"count": 42, "by_status": {"in_review": 35, "qa": 5, "in_progress": 2}, "threshold_days": 7,
                   "oldest": {"pr": "pr-30888b1", "display": "#104", "updated_at": "2026-03-23T13:13:51Z"}},
         "links": [{"label": "pm pr list -t", "command": "pm -C /home/matt/claude-work/project-manager/pm pr list -t"}]},
        {"id": "pos:828c8d0a", "kind": "position", "observation": "running", "required": false, "change": "new"}
      ]
    },
    {
      "key": "5e1c0a77", "name": "cosmic_ac", "pm_root": "/home/matt/claude-work/cosmic_ac/pm",
      "refresh": {"registry": "ok", "live": "ok", "registry_synced": "2026-11-02T14:26:10Z"},
      "position": {"open": {"in_progress": 2, "in_review": 2, "qa": 1, "sign_off": 1, "pending": 3},
                   "plans_touched": [{"id": "cmb-pipeline", "title": "CMB pipeline", "merged": 6, "total": 11}]},
      "next_action": {"item": "wait:5e1c0a77:pr-c46b7a2:merge-approval", "text": "Merge or hold #46 (signed off)"},
      "items": [
        {"id": "wait:5e1c0a77:pr-c46b7a2:merge-approval", "kind": "owner_decision", "observation": "waiting",
         "required": true, "change": "new", "since": "2026-10-31T15:05:00Z", "since_source": "signoff.ts", "age": "1d 23h",
         "pr": {"id": "pr-c46b7a2", "display": "#46", "title": "Refactor plotting helpers", "gh_pr": "https://github.com/fixture-owner/cosmic_ac/pull/46", "plan": "cmb-pipeline"},
         "facts": {"verdict": "SIGNOFF_MERGE", "fresh": true, "policy": "wait_for_merge",
                   "reason": "signed off (fresh SIGNOFF_MERGE); waiting for manual merge (held by pr-c46b7a2)"},
         "links": [{"label": "#46", "url": "https://github.com/fixture-owner/cosmic_ac/pull/46"},
                   {"label": "report", "url": "http://127.0.0.1:8765/p/5e1c0a77/pr-c46b7a2/report.html"}]},
        {"id": "fail:5e1c0a77:pr-c47e5d4:review-launch", "kind": "blocker", "observation": "failed",
         "required": true, "change": "new", "since": "2026-11-02T14:30:03Z", "since_source": "first_seen", "age": "new",
         "pr": {"id": "pr-c47e5d4", "display": "#47", "title": "Add HEALPix mask support", "gh_pr": "https://github.com/fixture-owner/cosmic_ac/pull/47", "plan": "cmb-pipeline"},
         "facts": {"reason": "review launch failed (needs attention): claude exited 1 before the first turn [artifact: /home/matt/.pm/transcripts/auto-77d1/review-pr-c47e5d4-i2.launch.log]"},
         "links": [{"label": "#47", "url": "https://github.com/fixture-owner/cosmic_ac/pull/47"},
                   {"label": "launch log", "path": "/home/matt/.pm/transcripts/auto-77d1/review-pr-c47e5d4-i2.launch.log"}]},
        {"id": "merge:5e1c0a77:pr-c41a2b0", "kind": "merged", "observation": "completed", "required": true, "change": "new",
         "since": "2026-11-01T22:12:00Z", "since_source": "merge_record.at",
         "pr": {"id": "pr-c41a2b0", "display": "#41", "title": "Add CMB power-spectrum loader", "gh_pr": "https://github.com/fixture-owner/cosmic_ac/pull/41", "plan": "cmb-pipeline"},
         "merge": {"mode": "auto", "via": "autostart", "detail": "auto-start auto_merge"}, "impact": "",
         "links": [{"label": "#41", "url": "https://github.com/fixture-owner/cosmic_ac/pull/41"},
                   {"label": "report", "url": "http://127.0.0.1:8765/p/5e1c0a77/pr-c41a2b0/report.html"}]},
        {"id": "merge:5e1c0a77:pr-c44d9e1", "kind": "merged", "observation": "completed", "required": true, "change": "new",
         "since": "2026-11-02T01:40:00Z", "since_source": "merge_record.at",
         "pr": {"id": "pr-c44d9e1", "display": "#44", "title": "Fix unit conversion in redshift binning", "gh_pr": "https://github.com/fixture-owner/cosmic_ac/pull/44", "plan": "cmb-pipeline"},
         "merge": {"mode": "owner", "via": "tui", "detail": "TUI merge action"}, "impact": "",
         "links": [{"label": "#44", "url": "https://github.com/fixture-owner/cosmic_ac/pull/44"},
                   {"label": "report", "url": "http://127.0.0.1:8765/p/5e1c0a77/pr-c44d9e1/report.html"}]},
        {"id": "pos:5e1c0a77", "kind": "position", "observation": "running", "required": false, "change": "new"}
      ]
    },
    {
      "key": "0e7a2b19", "name": "omerta-core", "pm_root": "/home/matt/claude-work/omerta/core/pm",
      "refresh": {"registry": "unavailable: project.yaml not found at /home/matt/claude-work/omerta/core/pm", "live": "not attempted"},
      "position": null, "next_action": null,
      "items": [
        {"id": "proj:0e7a2b19:unavailable", "kind": "unavailable", "observation": "unavailable", "required": true,
         "change": "new", "since": "2026-11-02T14:30:01Z", "since_source": "first_seen", "age": "new",
         "facts": {"reason": "project.yaml not found at /home/matt/claude-work/omerta/core/pm", "last_good": null}}
      ]
    }
  ],
  "guidance_changes": [],
  "headline": {"need_you": 2, "merged": {"auto": 1, "owner": 1, "unattributed": 4}, "blockers": 1,
               "not_refreshed": ["omerta-core"]}
}
```

## 7. The composer's draft for that run

`runs/20261102T143000Z-4f1a/draft.json`, composed under the setup guidance in
§1. It validates: every required id is referenced, no foreign ids appear, the
`#` numbers match, and there are 13 lines against a hard cap of 40 (about 25
was requested).

```json
{
  "schema": "pm.brief.draft/1",
  "run_id": "20261102T143000Z-4f1a",
  "sections": [
    {"project": "5e1c0a77", "title": "cosmic_ac", "lines": [
      {"text": "#46 Refactor plotting helpers is signed off and held for your merge.", "items": ["wait:5e1c0a77:pr-c46b7a2:merge-approval"]},
      {"text": "#47 HEALPix mask support: review could not start (claude exited before its first turn).", "items": ["fail:5e1c0a77:pr-c47e5d4:review-launch"]},
      {"text": "#41 Add CMB power-spectrum loader.", "items": ["merge:5e1c0a77:pr-c41a2b0"]},
      {"text": "#44 Fix unit conversion in redshift binning.", "items": ["merge:5e1c0a77:pr-c44d9e1"]},
      {"text": "2 in progress, 2 in review, 1 in QA, 1 at sign-off, 3 pending; CMB pipeline 6/11 merged.", "items": ["pos:5e1c0a77"]},
      {"text": "Next: merge or hold #46.", "items": ["wait:5e1c0a77:pr-c46b7a2:merge-approval"]}
    ]},
    {"project": "828c8d0a", "title": "project-manager", "lines": [
      {"text": "Spec for #287 (scheduled owner briefs) is waiting for your approval before implementation.", "items": ["wait:828c8d0a:pr-2588ead:spec-approval"]},
      {"text": "bugs plan: #272 PR close keeps history and workdirs; #280 no host fallback in container mode; #267 auto-start fails closed.", "items": ["merge:828c8d0a:pr-62ad13d", "merge:828c8d0a:pr-574e851", "merge:828c8d0a:pr-049649a"]},
      {"text": "improvements plan: #282 role-neutral model routing names and docs.", "items": ["merge:828c8d0a:pr-e076433"]},
      {"text": "42 open PRs have had no activity for 7+ days (oldest #104, since 23 Mar).", "items": ["idle:828c8d0a:*"]},
      {"text": "9 in progress, 36 in review, 7 in QA, none at sign-off, 391 pending; bugs 22/239 and improvements 14/57 merged.", "items": ["pos:828c8d0a"]},
      {"text": "Next: review the #287 spec.", "items": ["wait:828c8d0a:pr-2588ead:spec-approval"]}
    ]},
    {"project": "0e7a2b19", "title": "omerta-core", "lines": [
      {"text": "Could not refresh: project.yaml not found; no earlier data.", "items": ["proj:0e7a2b19:unavailable"]}
    ]}
  ],
  "guidance_notes": []
}
```

The rendered brief from this draft is [`briefs.md`](briefs.md) §B1.
