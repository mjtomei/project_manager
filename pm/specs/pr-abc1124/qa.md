# pr-abc1124 — QA spec: shared read-only image layers, private overlays, path separation, reclaim

Grounded in `git diff master...HEAD` (branch head 2cf70a53) and the
implementation spec (`pm/specs/pr-abc1124/impl.md`) / qualification record
(`pm/specs/pr-abc1124/qualification.md`).

## User-facing surfaces touched

| Surface | What changed |
|---|---|
| Any pm container launch (QA scenario containers from a QA loop, `pm qa regression/run/debug`, impl/review/sign-off containers) | `create_container` prepares/mounts a shared, read-only image-cache entry (provider) or refuses to build/pull inside a consumer; runs a subuid fit in every nested-podman container |
| `pm container status` | new `Image cache:` line (mode, entry, or why the cache is not used) |
| `pm container cache status / prepare / check / gc` | new |
| `pm container engine-setup [--home] [--force]` | new (in-container) |
| `pm container reclaim [--pr] [--dry-run]` | new |
| `pm pr cleanup --resources`, TUI merge cleanup, QA run start | now also reclaim disposable scenario engine stores / image archives |
| `pm set` | new `container-image-cache` (auto/on/off) and path settings `workdirs-dir`, `captures-dir`, `scratch-dir`, `image-cache-dir` (`default` clears; local-only ones refuse network filesystems) |
| QA run layout | scenario scratch moved from `<qa_workdir>/s-N/scratch` to `<scratch-dir or ~/.pm/scratch>/qa/<run>/s-N`; legacy dirs still honoured |
| `pm trust list` / auto-trust | approved roots include every workdirs root and QA scratch root |
| `pm pr dashboard`, sign-off record/merge gate | captures resolved across configured + default roots |
| QA recipes | new `pm/qa/instructions/nested-containers.md`; `tui-manual-test.md` container paragraph points to it |

## Shared resources inventory (each needs a concurrent-use story)

1. **Cache entry** `~/.pm/image-cache/entries/<key>/` (read-only to consumers), its per-key lock `locks/<key>.lock`, and `.prep-<key>-*` staging dirs / `pm-image-cache-prep-*` containers — racing preparers (threads in one QA loop, separate pm processes).
2. **Shared store bind mount** `/var/lib/pm-image-cache` — mounted into many concurrently running consumer containers; each consumer's private graphroot and CoW layers.
3. **Isolated engines inside one container** — several `HOME`s each with their own graphroot/runroot/tmp, reading the same lower layers concurrently.
4. **Scenario scratch dirs** `~/.pm/scratch/qa/<run>/s-N` — written by a live scenario while reclaim (manual, `pm pr cleanup`, QA-start background) may run; two reclaimers at once (`.pm-reclaiming-*` claim, `.pm-reclaim.json`).
5. **Cache GC vs. live consumers** — eviction after a new entry is published or by `pm container cache gc` while containers (any state) still reference an entry.
6. **Global settings files** (`~/.pm/settings/*`) — path settings changed while runs are in flight (scratch-dir mid-run, workdirs-dir / captures-dir with existing runs and evidence).
7. **Captures roots** (configured + default) read by dashboard / sign-off while new evidence is written.

## Setup (cross-cutting)

The QA scenario containers for this PR are launched by the host's installed
pm, which predates this PR, so they carry **no** shared cache. Every
container-based scenario therefore plays the host role itself, one nesting
level deeper than production (the same topology the implementer qualified):

1. Install this branch's pm in the scenario container (`./install.sh --local`
   from the clone, or the editable-install steps in TUI Manual Testing).
2. Build `pm-dev:latest` in the scenario container's own engine (`pm
   container build-base` from a `nested_podman: true` throwaway project, or
   `podman build --uts host` of the branch Dockerfile — a full ~4 min build).
   This is the one full image copy the scenario is allowed; it stands in for
   the host's image.
3. `pm set container-image-cache on` — `auto` deliberately does not provide
   from inside a container.
4. Throwaway project per TUI Manual Testing with `nested_podman: true`
   (bootstrap edit) and `pm container enable`; drive QA loops with
   fake-claude (scripted plan with ≥2 scenarios, scenario verdict delayed
   long enough to inspect the containers, `qa-worker-count` ≥ 2).
5. Topology consequence (expected, not a defect): containers the worker's
   pm launches are level-2; their root filesystem is fuse-overlayfs, so the
   default `/home/pm` engine there is refused with a "FUSE graphroot" message
   and engines must use a `HOME` on `/scratch` via `pm container
   engine-setup`. In production (host-launched consumers) the default
   engine works.

Measurements: wall time (`time`), allocated bytes (`du -sx --block-size=1`,
through `podman unshare` where files are sub-UID owned), network counters
(`/proc/net/dev`), `podman events`/`podman ps -a` for prep containers,
`podman images` (`R/O` column).

## Requirements (Given / When / Then)

### R1 Cold preparation happens once per image version
- **Given** branch pm acting as provider, `pm-dev:latest` built, cache `on`, a nested_podman container-mode project, and no cache entry,
  **When** the user starts a QA loop that launches scenario containers,
  **Then** one `pm-image-cache-prep-*` container appears and is removed, one entry appears under `~/.pm/image-cache/entries/<key>` (`pm container cache status` lists it with tags, size, prep seconds), and every scenario container starts with that entry mounted read-only (label `pm.image-cache=<key>`).
- **Given** that entry exists, **When** the user starts another QA run (or another launch), **Then** no prep container starts, the entry's `created_at` is unchanged, the extra launch latency is ~0.5 s, and no image pull/load/import or network download is observed.
- **Given** no launch yet, **When** the user runs `pm container status`, **Then** the `Image cache:` line says no entry exists yet and the next launch (or `pm container cache prepare`) prepares it — it does not prepare anything itself.

### R2 Simultaneous preparation is coordinated
- **Given** no entry, **When** two independent pm processes launch containers from the same image at the same time (and one QA loop launches ≥2 scenarios concurrently), **Then** exactly one preparation runs; the others wait and then reuse the published entry; one entry dir, no duplicate `.prep-*` left.
- **Given** a preparation killed mid-way (prep container and `.prep-*` dir left behind), **When** the user launches again, **Then** the leftovers are cleared under the lock, one entry is published, no stray prep container remains.

### R3 Tags vs. versions
- **Given** an entry for an image ID, **When** a second tag of the same ID is configured as the container image, **Then** the same entry is reused (no new prep).
- **Given** `pm-dev:latest` is rebuilt to a different image ID, **When** the user launches, **Then** a second entry is prepared; existing containers keep using the old one.

### R4 Writes are private; shared layers read-only; mappings correct
- **Given** two consumer containers running concurrently, **When** each runs a workload container from the shared image and writes into lower-layer paths, **Then** each write is visible only in its own engine/container, neither private graphroot contains the other's data, and the shared store's content (digest of names/sizes/owners/modes) is unchanged.
- **When** a user (as the engine user or `podman unshare` root) writes into `/var/lib/pm-image-cache`, **Then** it fails with `Read-only file system`; mountinfo shows the mount `ro`.
- **When** the user runs `pm container cache check`, **Then** all checks pass, including probes `uid0 0:0` / `uid1 1:1`; inside a workload `id -u` is 1000 and image-owned files keep their owners.
- **When** the user inspects a consumer's mounts, **Then** there is no host/parent podman socket and no shared writable graphroot — only the entry (`rw=false`) plus pm's usual mounts.

### R5 Isolated engines and build fixtures (Nested Containers recipe)
- **Given** a consumer container, **When** the user follows the Nested Containers instruction to set up two isolated engines (`HOME=/scratch/engines/wN pm container engine-setup`) and runs a container in each at the same time, **Then** both see the image `R/O=true`, start without pulling/importing, have distinct runroots/tmp dirs, and each graphroot holds only its own CoW layer.
- **When** the user builds the recipe's `FROM localhost/pm-dev:latest` fixture, **Then** only the new layers land in the private graphroot; base layers stay shared.
- **Given** an existing `storage.conf`/`containers.conf` pm did not write, **When** the user runs `engine-setup`, **Then** it refuses and names what the file needs; `--force` replaces it; re-running on a pm-written config succeeds.

### R6 Disk accounting
- **When** the user measures allocated bytes, **Then** the shared entry holds one copy of the image (~2 GB) and each scenario engine holds only its private changes (KB–MB plus build scratch), not a ~17 GB private store; the report states shared bytes, per-engine private bytes, build scratch and cold vs. warm timings rather than a fixed promised footprint.

### R7 Nested pm launch from inside a consumer
- **Given** a consumer container with branch pm and a nested_podman container-mode test project whose pm runs with a private `HOME` on `/scratch`, **When** that pm launches a container, **Then** it starts from the shared image without building, pulling or importing it (engine image list still only the `R/O` image), the private HOME's engine config is written automatically, and the launched (one level deeper) container has no `/var/lib/pm-image-cache`.
- **When** `pm container status` runs in the consumer, **Then** it reports `consumer of <key>` with the image tags.

### R8 Failures are actionable; no silent fallback
- Provider prep failure (image without podman), unwritable `image-cache-dir`, image not in the cache inside a consumer, FUSE graphroot, foreign engine config, overlay unavailable → a launch/setup error naming the cause and the remedies (`pm container cache prepare`, `pm set container-image-cache off`, `pm container set image`, `engine-setup`), no container launched, no prep container or partial entry left, no VFS selected, no host execution, never the generic "Is podman running?".
- `pm container cache prepare` inside a consumer is refused ("prepare entries on the host").
- `off` restores today's behaviour only by explicit choice; `auto` inside a non-consumer container does not provide and `pm container status` says so.

### R9 Lifecycle reclaim
- **Given** a finished container-mode QA run whose scenarios left engine stores, an image archive (`podman save` output) and drafts in scratch, **When** the user previews `pm container reclaim --dry-run`, **Then** it lists only stores/archives with sizes; held scratch dirs are listed with the reason (container mounts it, run still driven/resumable, process working in it, active mount).
- **When** the user runs it for real (or `pm pr cleanup --resources`), **Then** only stores and archives are deleted, drafts/configs/checkout/captures remain, a `.pm-reclaim.json` record is written, and the summary reports what was reclaimed.
- **When** a new QA run starts on the same PR, **Then** earlier runs' stores are reclaimed in the background without delaying the start.

### R10 Cache eviction
- An entry referenced by any container (running or stopped) is never evicted. An unreferenced entry whose image is gone or superseded (untagged after a rebuild) is evicted automatically after a new entry is published or by `pm container cache gc`; `--dry-run` previews; `--all-unreferenced` never removes the configured image's entry.

### R11 Path separation
- `pm set workdirs-dir|captures-dir|scratch-dir|image-cache-dir <abs path>` accepted; relative paths refused; `default` restores; `pm set list` shows them. `scratch-dir` and `image-cache-dir` refuse a network filesystem naming the setting; `workdirs-dir` and `captures-dir` accept one.
- After moving `workdirs-dir`/`captures-dir`, a new QA run puts the checkout and captures there while scratch and engine graphroots stay local; Git (commit, push to a remote) and container launches work from the moved checkout.
- Existing runs/evidence keep working: an earlier run under the default root is still found (resume, latest status, sign-off gate), a PR whose evidence already existed keeps writing to its old captures dir (no split, no "report.html changed"), and the dashboard serves reports from both roots.
- `pm trust list` lists every workdirs and QA-scratch root; a host-mode scenario's throwaway project in the new scratch root does not stall at the trust prompt.
- A `scratch-dir` change mid-run does not hand a relaunched in-flight scenario an empty scratch.

## Edge cases

- **Damaged entry while in use**: Given a consumer is running from an entry whose `entry.json` is later damaged/removed, When another launch of that image happens, Then the running consumer keeps working (its layers are not deleted out from under it) — the PR requires shared layers needed by active consumers never be evicted; if pm cannot safely replace the entry it must say so.
- Image rebuilt while preparation is running → prep fails with "loaded image ID differs … retry", nothing published.
- Stopped-but-not-removed scenario container → its scratch is held.
- Scratch dir that is itself a container store (engine run with `--root` on it) → held, not deleted.
- Two reclaimers at once → each item removed once, no errors, no half-store left (an interrupted claim is finished by the next pass).
- Runtime unavailable during reclaim/gc → nothing deleted, summary says the runtime could not be listed.
- A tag added on the host after an entry exists is not visible to consumers (entries immutable); the consumer's missing-image error lists the tags it does have.
- Level-3 containers (launched by a nested pm) get no cache by design; `pm container cache check` there says the cache is not mounted.

## Pass / fail criteria

Pass: each Then above is observed through pm's CLI/TUI or plain podman/filesystem inspection a user would do; errors are actionable and name remedies; no extra image copies, pulls or imports appear in consumers; reclaim/GC never remove held/referenced data.

Fail: a second preparation for the same image ID; a consumer or nested pm that builds/pulls/loads the image; a writable or modified shared store; data visible across engines; a launch that silently proceeds without the cache, selects VFS or runs on the host; a generic/opaque error; reclaim or GC deleting drafts, checkouts, captures, live scratch or a referenced entry; settings accepted for local-only paths on network storage; evidence or runs lost after a path setting change.

## Ambiguities (resolved)

1. **Scenario topology** — scenario containers come from a pre-PR host pm, so each scenario plays the host inside its container with `container-image-cache on` (one level deeper than production). The default-engine FUSE-graphroot refusal in level-2 containers is expected at this depth; engines use `HOME` on `/scratch`.
2. **NAS** — no NAS is available. Network storage is simulated with a FUSE mount whose type reports a network filesystem (e.g. `-o subtype=sshfs`) or skipped where that is impossible; real-NAS Git/container qualification is reported as outstanding, not passed.
3. **VFS comparison** — not re-measured per scenario (the implementer measured ~16.9 GB once); scenarios measure shared vs. private bytes.
4. **Damaged in-use entry** — the PR description ("do not evict shared layers needed by active or retained consumers") governs: a running consumer must not lose its layers.
5. **Image for failure fixtures** — an image without podman (e.g. a pulled `alpine`/`ubuntu`) is a bounded representative fixture for preparation failure.
