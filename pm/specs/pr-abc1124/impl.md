# pr-abc1124 — Shared read-only image layers and private overlays for nested QA containers

Implementation spec (Step 0).  Spec review is off for this PR (owner update,
2026-11-26): this file is recorded as usual and implementation proceeds
directly from it.

## 0. Summary of the design

* **One cache entry per image version, prepared once on the host.**  An entry
  is keyed by the full image ID (content digest), not the tag, so two
  different `pm-dev` builds get two entries and identical IDs under several
  tags share one.  The entry is a containers/storage *overlay* store that
  holds the image's unpacked layers exactly once, prepared by one
  `podman save <ref> | podman exec -i <prep> podman --root … load` stream
  (no archive file is written).  The prep container is started from the same
  image with the same `--userns=keep-id` + nested-podman flags as consumers,
  so the store's file ownership is what consumers' rootless engines expect.
* **Consumers mount the entry read-only and use it as an additional image
  store.**  `create_container` bind-mounts the entry at
  `/var/lib/pm-image-cache` (`:ro`) and writes the default user's
  `~/.config/containers/storage.conf`: overlay driver, `fuse-overlayfs`
  mount program, a private writable graphroot on container-local disk, and
  `additionalimagestores = ["/var/lib/pm-image-cache/store"]`.  Every engine
  keeps its own graphroot; only copy-on-write container layers and
  genuinely new (built) layers are private.
* **Nested pm launches reuse it.**  A pm running inside a consumer (a test
  project's container-mode pm) never prepares, builds or imports the image:
  its engine sees the shared image, and if the image is not there it fails
  with an actionable error.
* **Paths are separated.**  Source workdirs and evidence (captures) may be
  configured onto a NAS; scratch, the image cache, container storage and
  runtime dirs must be local and are refused on a network filesystem.  QA
  scenario scratch moves out from under the scenario workdir.
* **Lifecycle reclaim.**  Disposable scenario engine stores and image
  archives under scenario scratch are reclaimed by the existing PR cleanup
  and QA-run-start hooks (plus a previewable manual command) only when no
  container still mounts that scratch, the run is not live and the
  container is not retained.  Cache entries are evicted only when no
  container references them and their image is gone from the host.

## 1. Grounding — what the code and runtime do today

Code (master @ c3bac6ce, this branch @ 9c45c377):

* `pm_core/container.py:create_container` (l.720–1139) builds a
  `podman run -d … --userns=keep-id` command; with `nested_podman: true`
  (`_nested_podman_enabled`, l.122) it adds `_nested_podman_run_args`
  (`/dev/fuse`, `/dev/net/tun`, `unmask=ALL`, `--uts=host`, AppArmor/SELinux
  relaxations).  No container storage is mounted, so a nested engine's
  graphroot is `~/.local/share/containers/storage` inside the container's own
  rootfs, or wherever a scenario points `HOME`/`--root`.
* The Dockerfile (l.84–90) writes `/etc/containers/storage.conf` with
  `driver = "overlay"` + `mount_program = "/usr/bin/fuse-overlayfs"` and
  `/etc/containers/containers.conf` with `netns = "host"`.
* `create_container` auto-builds `pm-dev:latest` when it is missing
  (l.773–778): inside a container that means a full `podman build` from the
  Dockerfile (network + several GB) per engine.
* `pm_core/qa_loop.py:create_scenario_workdir` (l.395) puts scratch at
  `{qa_workdir}/s-N/scratch`, i.e. under `~/.pm/workdirs/qa/<pr>-<loop>/`;
  `_relaunch_container_if_gone` (l.3720) and the tmux prompt (l.3645)
  recompute it the same way; `cli/qa.py` regression (l.484) and debug
  (l.829) runs reuse `create_scenario_workdir`.  `create_qa_container`
  mounts scratch at `/scratch`.  Nothing ever deletes QA run dirs, so
  stores created under scratch persist forever.
* `pm_core/paths.py`: `workdirs_base()` is fixed at `~/.pm/workdirs`; six
  places in `qa_loop.py`/`tui/qa_loop_ui.py`/`cli/qa.py` hard-code
  `~/.pm/workdirs/qa`; `captures_dir`/`captures_root` are the single source
  of captures paths (`~/.pm/sessions/<tag>/captures/<pr>`).
* Lifecycle today: `pr_cleanup.cleanup_pr_resources` (merged/closed PRs, TUI
  sync, `pm pr cleanup`) removes a PR's containers; `qa_loop` calls
  `cleanup_orphaned_qa_containers` at QA start; `pm container cleanup`
  removes containers manually.  pr-1139060 (#241, unmerged) adds
  `container_reaper.py` with retention markers (`is_retained`) and
  ownership-checked reconciliation; pr-cd04629 (#290, unmerged, audit stage)
  proposes `required_container_launch()` / `ensure_container()` with
  `create_container` delegating to it.
* The shared QA recipe `pm/qa/instructions/tui-manual-test.md` says only
  "opt into `nested_podman`"; nothing in the repo tells scenarios how to get
  an image into a nested engine.  The VFS / save-load / rebuild habits live in
  scenario plans and agent notes (e.g. "two stores: separate storage.conf …
  `podman save`/`load` ~10 s", "private VFS store", "private HOME needs
  fuse-overlayfs storage.conf").

Runtime facts measured in this impl container (podman 3.4.4, crun,
fuse-overlayfs 1.7.1, kernel 7.0, rootless, keep-id):

1. `podman --root X` (or `--runroot`) **drops the configured
   `mount_program`**: `'overlay' is not supported over overlayfs, a
   mount_program is required`.  With a private root on the overlayfs
   container rootfs the only flag-free driver that works is VFS — the most
   likely origin of the routine VFS overrides.
2. `additionalimagestores` / `overlay.imagestore` works for rootless
   overlay+fuse-overlayfs: two engines with private graphroots ran
   containers from one store; each private store held only its ~200 KB
   container layer; writes landed in the private `diff/`; the shared store
   was unchanged.
3. **Rootless podman ignores `additionalimagestores` from the system config**
   (`/etc/containers/storage.conf`, and also a file named by
   `CONTAINERS_STORAGE_CONF`): only `ignore_chown_errors` and the driver are
   carried into the rootless defaults.  It is honoured from the user config
   (`$XDG_CONFIG_HOME` or `$HOME/.config/containers/storage.conf`) or
   `--storage-opt`.  Hence pm writes the *user* config inside each consumer.
4. Runroot paths longer than 50 characters are rejected
   (`the specified runroot is longer than 50 characters`).
5. A *foreground* `podman run` in a pm container hangs after the workload
   exits (its exit-command cleanup blocks; PID 1 is `sleep infinity` and
   does not reap the `fuse-overlayfs` child — the known pr-2111fa0 class).
   pm itself always uses `run -d` + `exec` + `rm -f`; preparation and
   qualification do the same.
6. Each keep-id nesting level shifts non-root IDs by one: level-L container
   uid `u` (1 ≤ u < 1000) maps to `u+1` one level up.  Root maps to root at
   every level.  A store prepared for consumers at level L therefore shows
   non-root image files one ID off to an engine at level L+1.
7. (Found during implementation.)  In a container launched from inside a
   container, rootless engines cannot start at all: its uid_map is
   `0 1 999; 999 1000 1; 1000 0 1; 1001 1001 64534`, the image's
   `/etc/subuid` (`pm:1:999`, `pm:1001:64535`) spans two parent extents and
   names a uid that does not exist, and the kernel accepts a new extent only
   inside one parent extent → `newuidmap: write to uid_map failed:
   Operation not permitted`.  Splitting the ranges at the container's own
   extent boundaries (`pm:1:998`, `pm:999:1`, `pm:1001:64534`) fixes it; for
   a host-launched container the image's ranges already fit and nothing
   changes.  pm applies this fit as a root setup step in every
   nested-podman container (and the prep container).
8. (Found during implementation.)  In such a container the root filesystem
   is the parent engine's fuse-overlayfs mount; a graphroot there "mounts"
   containers without invoking the mount program and every workload fails
   with `executable file not found`.  A graphroot on a bind-mounted
   directory (`/scratch`) works.  Host-launched containers have a native
   overlay rootfs, so their default graphroot is fine (as in this impl
   container).  `engine-setup` and `cache check` refuse a FUSE graphroot
   with the fix.

The audit evidence paths named in the task
(`/home/matt/.local/state/pm-pr-shepherd/disk-audit-20261105T040137Z`,
`…/initial-disk-cleanup-20261112T235652Z`) are on the host and are **not
mounted in this impl container**; the spec relies on the numbers quoted in
the task and on the measurements above.

## 2. Requirements

### R1 — Cache entries: prepared once per image version (`pm_core/image_cache.py`, new)

* `cache_root()` = setting `image-cache-dir` or `~/.pm/image-cache`;
  validated local (R5).  Layout:
  `entries/<key>/{store/, probe/, entry.json}`, `locks/<key>.lock`,
  `entries/.prep-<key>-<rand>/` while preparing.
* `key` = first 20 hex chars of the image ID (`sha256:` stripped).  Tags are
  metadata; a rebuilt image gets a new key and a new entry; the old entry is
  retained while anything still references it (R7).
* `ensure_prepared(image_ref)`:
  1. resolve `image_ref` to its full ID and RepoTags on the host runtime;
  2. if `entries/<key>/entry.json` exists with `format_version == 1` and the
     same ID, return it (warm path: no runtime calls beyond the inspect);
  3. otherwise take `locks/<key>.lock` (`fcntl.flock`, bounded wait — default
     30 min, the prep is idempotent) and re-check — this is the coordination
     for simultaneous requests from threads and processes;
  4. prepare in a fresh `.prep-*` dir: start a prep container
     (`run -d --userns=keep-id <nested args> --label pm.image-cache-prep=<key>
     -v <prep-dir>:/var/lib/pm-image-cache <image-id> sleep infinity`),
     stream `podman save <ref>` into
     `podman exec -i <prep> podman --root /var/lib/pm-image-cache/store
     --runroot /tmp/pm-cache-prep --storage-driver overlay
     --storage-opt overlay.mount_program=/usr/bin/fuse-overlayfs load`, add
     every host tag of the ID with `podman tag`, verify the loaded ID equals
     the host ID, write mapping probes with `podman unshare` (`probe/uid0`
     owned 0:0, `probe/uid1` owned 1:1), remove the prep container;
  5. write `entry.json` (image id, names, ref, runtime + version, prep
     seconds, store bytes, created_at, format_version) into the prep dir and
     publish it with one `rename` to `entries/<key>`;
  6. after a successful publish, evict stale entries (R7).
* Any failure raises `ImageCacheError` whose message names the cause and
  the remedies (fix and retry / `pm container cache prepare` /
  `pm set container-image-cache off`); the partial prep dir and container
  are removed.

### R2 — Consumer wiring in the existing launch path (`pm_core/container.py`)

* Setting `container-image-cache`: `auto` (default) | `on` | `off`.
  * Provider (prepare + mount) is active when the runtime is podman, the
    project has `nested_podman: true`, and either the mode is `on`, or the
    mode is `auto` and pm is not itself running inside a container
    (`/run/.containerenv` / `/.dockerenv` absent).
  * Consumer mode is active inside a container that has
    `/var/lib/pm-image-cache/entry.json`, unless the mode is `off`.
* `create_container` (new-container path only; the reuse path is
  unchanged):
  * provider active → `image_cache.ensure_prepared(config.image)` after the
    existing image existence/auto-build step; add
    `-v <entry>:/var/lib/pm-image-cache:ro`,
    `--label pm.image-cache=<key>`, `-e PM_IMAGE_CACHE=/var/lib/pm-image-cache`,
    and a setup step that writes the default user's engine config (R3).
    `ImageCacheError` becomes `ContainerError` — no launch without the
    cache, no VFS, no host fallback.
  * consumer active (pm inside a consumer launching its own containers) →
    never prepare, never auto-build: the default image must be visible
    through the shared store (`image_exists`), else `ContainerError` naming
    the cached image and the host-side remedy.  The engine config for the
    current `HOME` is ensured first (a test pm with a private `HOME`).  The
    shared entry is **not** mounted into the next level (fact 6); see A3.
* `pm container status` shows the cache mode and, when applicable, the
  entry for the configured image.

### R3 — Engine configuration (`image_cache.engine_config`, `pm container engine-setup`)

* One generator produces `storage.conf` (+ `containers.conf` for isolated
  engines) for a given `HOME`: `driver = "overlay"`, `graphroot =
  $HOME/.local/share/containers/storage`, `mount_program =
  /usr/bin/fuse-overlayfs`, `additionalimagestores = [store]`.  Isolated
  engines also get `runroot = /tmp/pm-eng-<hash8>/run` (≤ 50 chars) and
  `[engine] tmp_dir = /tmp/pm-eng-<hash8>/tmp`, so two engines in one
  container never share runtime state.
* The default engine (`/home/pm`) is written by `create_container`'s setup
  script from the same generator (no runtime dependency on pm inside the
  image).
* `pm container engine-setup [--home DIR]` (in-container) writes the config
  for `DIR` (default `$HOME`), refuses an existing config that it did not
  write unless `--force`, refuses a graphroot on a network filesystem, and
  runs the consumer check.
* `pm container cache check` (in-container) verifies: entry present,
  engine config references the store, graphroot local, mapping probes read
  `0:0` / `1:1` through `podman unshare stat`, configured image visible
  (`R/O`).  Non-zero exit with the fix on any failure.

### R4 — Lifecycle reclaim (`pm_core/storage_reclaim.py`, new)

* Disposables inside a scenario scratch dir: container stores (a dir with
  `storage.lock` plus `overlay-layers|vfs-layers|overlay-images|vfs-images|
  libpod`) and uncompressed image archives (a tar whose members include
  `manifest.json` plus `repositories` or `oci-layout`/`index.json`; headers
  only are read).  Nothing else is touched: no checkout, captures,
  transcripts, notes, drafts, recordings or other scratch files.
* A scratch dir is **held** (skipped) when any existing container (running
  or stopped) mounts it or a parent/child of it, when its run is live (run
  record without `ended_at` whose owner process is alive), when the runtime
  cannot be listed (fail safe), when a store has an active mount beneath it
  (`/proc/self/mountinfo`), or — once pr-1139060 lands — when
  `container_reaper.is_retained` says so for the scenario container.
* Deletion uses `podman unshare rm -rf` for stores (their files are owned by
  sub-UIDs) and `unlink` for archives; a `.pm-reclaim.json` record (paths,
  bytes, time, reason) is left in the scratch dir.
* Hooks (existing lifecycle owners only — no new scheduler):
  * `pr_cleanup.cleanup_pr_resources`, after containers are removed:
    reclaim every run of that PR (`summary["reclaimed"]`).
  * QA run start (`qa_loop`, where `cleanup_orphaned_qa_containers` runs):
    reclaim earlier runs of the same PR in a daemon thread so the run
    start is not delayed.
  * `pm container reclaim [--pr PR] [--dry-run]`: preview and outcome
    summary.

### R5 — Path separation (`pm_core/paths.py`, `pm set`)

* New path settings via `pm set <name> <path>` (`pm set <name> default`
  clears):
  * `workdirs-dir` — PR, meta and QA source workdirs (may be a NAS);
    `workdirs_base()` honours it; all hard-coded `~/.pm/workdirs/qa` uses go
    through a new `qa_workdirs_root()`.
  * `captures-dir` — retained evidence (may be a NAS); `captures_dir` /
    `captures_root` resolve `<captures-dir>/<tag>/<pr>`.
  * `scratch-dir` — local scratch (default `~/.pm/scratch`).
  * `image-cache-dir` — local image cache (default `~/.pm/image-cache`).
* `filesystem_type(path)` (longest mount-point prefix in
  `/proc/self/mountinfo` of the deepest existing ancestor) and
  `require_local_path(path, purpose, setting)`: network types (nfs*, cifs,
  smb*, 9p, ceph, glusterfs, lustre, afs, gpfs, beegfs, davfs, fuse.sshfs,
  fuse.rclone, fuse.s3fs, fuse.glusterfs, …) raise `NonLocalPathError` with
  the setting to change.  Applied to scratch, the image cache and engine
  graphroots.
* `paths.scenario_scratch_dir(qa_workdir, index)` = the legacy
  `{qa_workdir}/s-N/scratch` if it already exists (in-flight runs keep their
  mounts), else `scratch_base()/qa/<qa_workdir.name>/s-N`.  Used by
  `create_scenario_workdir`, the tmux prompt and the relaunch path.
* No migration of existing workdirs/captures; changing a setting affects
  new paths only (documented in `pm set` help).

### R6 — Shared recipe/instructions

* New `pm/qa/instructions/nested-containers.md` (full text in §6) is the one
  place describing nested-engine defaults.
* `pm/qa/instructions/tui-manual-test.md` container-mode paragraph points
  to it (full revised text in §6).
* The QA planning prompt (`prompt_gen.py`, "Within a single scenario you
  *can* spawn nested containers…") points planners at that instruction
  instead of restating storage setup.
* Dockerfile: comment-only change next to the storage.conf step (no layer
  change, so no image rebuild is forced).

### R7 — Cache eviction

* An entry is **referenced** while any container (any state) carries
  `pm.image-cache=<key>` or a prep container carries
  `pm.image-cache-prep=<key>`.
* Automatic eviction after a new entry is published, and
  `pm container cache gc [--dry-run] [--all-unreferenced]`: remove
  unreferenced entries whose image ID no longer exists on the host
  (`--all-unreferenced` also removes unreferenced entries whose image still
  exists, except the configured image's), and abandoned `.prep-*` dirs with
  no live prep container.  Removal uses `podman unshare rm -rf`.

## 3. Implicit requirements

* The prep container must use the same user-namespace flags as consumers
  (keep-id + `_nested_podman_run_args`) and the same in-container path
  (`/var/lib/pm-image-cache`), or ownership/paths differ.
* The consumer engine config must set `mount_program`; the store must be
  prepared with the same driver options it is consumed with.
* The image must be saved by tag (an ID-only save loads untagged); every
  host tag of the ID is re-applied so any configured alias resolves.
* The image ID after load must equal the host ID (docker-archive keeps the
  config digest); a mismatch aborts the prep.
* Everything under `store/` is sub-UID owned on the host: host-side deletion
  needs `podman unshare`; host-side reads (du) may need it too.
* The prep must not hold the image-cache lock across unrelated entries —
  one lock per key, so two different images prepare concurrently.
* `create_container` must not block the existing reuse path and must keep
  secrets out of logged command lines (unchanged).
* Tests must never touch the real `~/.pm`, the live host runtime or real
  settings: unit tests patch `HOME`, `_run_runtime` and subprocess; an
  autouse fixture turns the cache `off` and stubs background reclaim.
* Rootless engines must be able to start in every nested-podman container
  pm creates, at any depth (fact 7): `create_container` and the prep
  container run the subuid fit as root after setup.
* A store being reclaimed is first renamed (`.pm-reclaiming-*`) so a
  deletion cut short is finished by the next pass rather than leaving an
  unrecognisable half-store.

## 4. Ambiguities and resolutions

* **A1 — Which engines are "independent scenario engines"?**  The engines
  inside pm-launched containers (QA scenario, impl, review, sign-off) and any
  isolated engine a scenario starts with a private `HOME` inside its
  container.  Resolution: wire the default engine automatically; isolated
  engines run one `pm container engine-setup` (recipe).
* **A2 — Default on or off?**  Resolution: `auto` = on for nested_podman
  projects on a podman host, off inside non-consumer containers (so an
  existing nested container without a mounted cache keeps today's
  behaviour).  `on` forces the provider anywhere (qualification from inside
  this impl container uses it); `off` restores today's behaviour everywhere.
* **A3 — "including further nested PM containers".**  A pm inside a
  consumer launches its containers from the shared image without preparing,
  importing or copying it (R2, consumer mode).  Containers one level deeper
  do not get the entry: keep-id shifts non-root IDs by one per level
  (fact 6), so the same bytes cannot be correct at two depths, and
  preparing a deeper entry inside each scenario would recreate the
  per-scenario duplication.  Engines at that depth keep today's behaviour;
  the probe check makes a mis-mounted entry fail loudly.  Recorded as a
  limitation with a follow-up option (host-prepared per-depth entries keyed
  by mapping).
* **A4 — "no silent fallback" vs. today's auto-build.**  With the cache
  active, a missing/incompatible entry or failed prep is a launch error
  (provider) or a nested launch error (consumer); pm neither builds pm-dev
  in the nested engine nor launches without the mount.  With the cache
  `off`, behaviour is unchanged.
* **A5 — Where may graphroots live?**  Container-local disk (the default
  `HOME`), `/scratch` (now local) or `/tmp`.  Never `/workspace`: the
  checkout may be on a NAS.  `engine-setup` and the consumer check refuse a
  network filesystem.
* **A6 — What may reclaim delete?**  Only container stores and image
  archives inside scenario scratch, only when held by nothing (R4).
  Everything else in scratch is kept: it can be drafts or investigation
  artifacts.  "After saving evidence": evidence is written to the captures
  dir during the run; reclaim never runs while the run is live or its
  container exists.
* **A7 — NAS qualification.**  No NAS is mounted in this impl container.
  Path separation is verified with a simulated network mount type (tests)
  and a separately located workdir root; real NAS Git/container access is
  reported as **outstanding**.
* **A8 — Image-build tests.**  Allowed in the private graphroot with a small
  `FROM localhost/pm-dev:latest` fixture; rebuilding pm-dev from the
  Dockerfile stays possible but is called out as a full build.
* **A9 — Docker runtime.**  The cache is podman-only (it relies on rootless
  user config, `unshare`, fuse-overlayfs); Docker containers are unchanged.
* **A10 — Coordination with #241/#290.**  No hard prerequisite.  Reclaim
  uses `container_reaper.is_retained` only if that module exists;
  `ImageCacheError` surfaces as `ContainerError`, which #290's
  `required_container_launch` already treats as a fail-closed launch
  failure.  Notes are left on both PRs.

## 5. Edge cases

* Two QA runs (two processes) launch scenarios while no entry exists: one
  prepares, the others wait on the per-key lock, then all reuse the entry.
* The host image is rebuilt while a prep is running: the loaded ID will not
  match the resolved ID → prep fails and is retried on the next launch.
* An entry is deleted by hand while containers mount it: their engines lose
  the image; the next launch re-prepares.  GC never deletes referenced
  entries.
* A scenario sets a private `HOME` and runs `podman` without
  `engine-setup`: rootless defaults apply (overlay via fuse-overlayfs from
  the system config, no shared image) — the recipe says to run
  `engine-setup`; pm's own nested launches do it automatically.
* An existing user `storage.conf` written by the scenario: `engine-setup`
  refuses to overwrite it without `--force` and says why.
* In-flight QA runs across the upgrade: legacy scratch dirs keep being used
  (R5), their containers keep their mounts.
* Stopped (not removed) scenario containers hold their scratch → no
  reclaim until they are removed.
* A scratch dir unreadable in places (sub-UID owned): walk errors are
  skipped, never fatal.
* `pm container reclaim` with the runtime down: nothing is deleted; the
  summary says the runtime could not be listed.
* `podman save` → load is a full import exactly once per image version per
  cache root; a second user/cache root prepares its own.

## 6. Revised recipe / instruction text (complete)

### 6.1 New file `pm/qa/instructions/nested-containers.md`

```markdown
---
title: Nested Containers
description: Run podman — and container-mode pm — inside a QA or impl container using the shared, host-prepared image cache. Covers the defaults, isolated engines, nested pm launches, image-build fixtures and cleanup. No rebuilds, no save/load, no VFS.
---
## What is already set up

When pm launches a container for a project with `nested_podman: true` on a
podman host, it prepares a shared, read-only copy of the container's image
once per image version and mounts it into the container:

- `/var/lib/pm-image-cache/` — the shared image store (`store/`), mapping
  probes and `entry.json` (image ID and tags). It is read-only and shared by
  every container launched from that image version; never write to it.
- `~/.config/containers/storage.conf` for the default user — overlay
  driver, `fuse-overlayfs`, a private writable graphroot at
  `~/.local/share/containers/storage` (container-local disk), and the shared
  store as an additional image store.

So `podman images` already lists the image (column `R/O` = `true`), and
`podman run -d --uts host pm-dev:latest …` starts with only a private
copy-on-write layer. Check the setup at any time:

    pm container cache check

It exits non-zero and names the fix when something is wrong. If it says the
cache is not mounted, this container was launched without it (cache `off`,
Docker, or no `nested_podman`); ask instead of working around it.

## Don't

- Don't select VFS (`--storage-driver vfs`, `driver = "vfs"`,
  `STORAGE_DRIVER=vfs`). VFS copies every parent layer: a ~2 GB image
  becomes a ~17 GB store. Only a scenario whose subject is the storage
  driver picks a driver explicitly (see below).
- Don't `podman save` / `podman load`, `podman pull` or rebuild pm-dev to get
  the image into an engine. It is already visible.
- Don't pass `--root` / `--runroot` by hand. Podman 3.4 then drops the
  configured `mount_program`, overlay fails on the container's overlayfs
  root filesystem, and the shared store is not used. Use a private `HOME`
  with `pm container engine-setup` instead.
- Don't put a private `HOME`, graphroot or runroot under `/workspace`: the
  checkout may live on network storage. Use `/scratch` or `/tmp`.
- Don't copy stores or image archives into `/pm-captures`.

## Isolated engines (separate workers)

Each engine gets its own graphroot, runroot and tmp dir; all of them read
the same shared layers:

    for w in w1 w2; do
      HOME=/scratch/engines/$w pm container engine-setup
    done
    HOME=/scratch/engines/w1 podman run -d --uts host --name w1 pm-dev:latest sleep infinity
    HOME=/scratch/engines/w2 podman run -d --uts host --name w2 pm-dev:latest sleep infinity

`engine-setup` refuses a network filesystem, an incompatible cache, and an
existing `storage.conf` it did not write (`--force` replaces it).

## Container-mode pm inside the container (nested pm launch)

Opt the throwaway project into nested podman (`nested_podman: true`, a
bootstrap-only `project.yaml` edit — see TUI Manual Testing) and run
`pm container enable`. The nested pm launches its containers from the
shared image: it never builds, pulls or imports it, and a pm started with a
private `HOME` gets its engine configured automatically. If the image is
not in the shared cache the launch fails with an error naming the cached
image — it does not fall back to building, VFS or the host.

Containers launched by that nested pm (one level deeper) do not receive the
shared cache: each nesting level shifts non-root file ownership by one, so
the store is only valid at the level it was prepared for. Don't run podman
inside those deeper containers unless that is what the scenario tests; if
it is, give the engine a HOME on a bind-mounted directory such as
`/scratch` — their root filesystem is itself a fuse-overlayfs mount, where
podman cannot mount containers.

## Image-build tests

Build a small fixture on top of the cached image instead of rebuilding
pm-dev:

    mkdir -p /scratch/build-fixture && cd /scratch/build-fixture
    printf 'FROM localhost/pm-dev:latest\nRUN echo fixture > /etc/pm-fixture\n' > Containerfile
    podman build --uts host -t localhost/pm-fixture:test .

New layers land in your private graphroot; the base layers stay shared.
Rebuild pm-dev from the Dockerfile only when the Dockerfile itself is under
test — that is a full build (network, several GB, minutes); say so in the
scenario's steps.

## Explicit storage-driver tests

A scenario about storage drivers may choose one explicitly: use a private
`HOME` under `/scratch` with its own `storage.conf` naming the driver, and a
small image (a pulled `alpine`, or the build fixture above) — not pm-dev.

## Cleanup

Remove what you started (`podman rm -f <name>`). After the scenario's
container is gone and the run has ended, pm reclaims engine stores and image
archives left under `/scratch`; the checkout, `/pm-captures` and other
scratch files are never touched.
```

### 6.2 Revised paragraph in `pm/qa/instructions/tui-manual-test.md` (step 3)

```markdown
   **Testing container-mode features (nested podman):** if your test
   exercises pm's container mode — e.g. a container-mode QA loop, where the
   test project's pm launches scenario containers from *inside* the
   container this test session already runs in — you must opt the test
   project into nested podman. Add to its `pm/project.yaml` under the
   `project:` block:
   ```yaml
   project:
     nested_podman: true
   ```
   Without it, the inner `podman run` is launched without the
   nested-podman flags (notably `--uts=host`) and dies with
   `sethostname: Operation not permitted` before any scenario starts —
   because the surrounding container has no `CAP_SYS_ADMIN` and a seccomp
   filter that blocks `sethostname`. This is bootstrap-only project.yaml
   setup (same exception as the status edits above); enable container mode
   itself through the normal surface (`pm container enable`). The pm-dev
   image ships the other nesting prerequisites (uidmap file caps,
   `/etc/subuid` for `pm`, fuse-overlayfs), and pm mounts the shared image
   cache, so the nested pm uses pm-dev without building or copying it.
   Follow the **Nested Containers** instruction for everything about nested
   engines (isolated engines, image-build fixtures, what not to do — no VFS,
   no save/load, no rebuilds).
```

### 6.3 QA planning prompt (`pm_core/prompt_gen.py`)

Current:

> Within a single scenario you *can* spawn nested containers, background
> processes, or parallel actors to drive the system under test from
> multiple contexts at once — use that capability whenever the surface
> being tested is shared across users or workers.

Revised (one sentence appended):

> Within a single scenario you *can* spawn nested containers, background
> processes, or parallel actors to drive the system under test from
> multiple contexts at once — use that capability whenever the surface
> being tested is shared across users or workers. Nested containers use the
> shared image cache described in the Nested Containers instruction;
> reference that instruction instead of writing storage-driver, image
> import or rebuild steps into STEPS.

## 7. Qualification plan (recorded in `pm/specs/pr-abc1124/qualification.md`)

Topology available here: this impl container plays the host; containers it
launches through `create_container` play the scenario containers; a pm
inside one of them plays the nested PM launch.

1. Cold prep (time, bytes, `/proc/<pid>/io`, network counters) of the real
   pm-dev image; warm `ensure_prepared` and warm starts of two concurrent
   consumers plus a nested pm launch from one of them; verify no pull, no
   load, no layer copy (store and graphroot byte counts, image `R/O`).
2. Private writes: markers written in each worker visible only there; the
   shared store's file list/checksums unchanged; the mount is `ro`
   (write attempt fails with EROFS); probe IDs `0:0`/`1:1`; no host socket
   or shared writable graphroot mounted (inspect mounts).
3. Failure modes: missing entry in a consumer, incompatible probe, missing
   fuse-overlayfs/`/dev/fuse`, prep failure, network-filesystem path →
   actionable errors, no fallback (unit tests + real runs where feasible).
4. Disk: allocated bytes (`du`) of the shared store vs. each private
   graphroot vs. a VFS store of the same image (measured once for the
   comparison), and build-fixture scratch.
5. Reclaim: stores + archives in a finished scenario's scratch reclaimed;
   held/live/retained cases kept; checkout and captures untouched.  NAS:
   outstanding (A7).

## 8. Out of scope

Memory/concurrency governance; migrating historical scenario plans or
agent notes; NAS provisioning; automatic migration of existing workdirs or
captures; per-depth (level ≥ 2) cache entries (A3); Docker-runtime caching.
