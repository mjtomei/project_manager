# pr-abc1124 — Qualification of the shared image cache

Measured 2026-11-26 in the pm impl container (aarch64, podman 3.4.4, crun,
fuse-overlayfs 1.7.1, kernel 7.0, rootless, keep-id).  Raw evidence is in
this PR's captures dir (`/pm-captures/qual/` in the container,
`~/.pm/sessions/<tag>/captures/pr-abc1124/qual/` on the host).

## Topology and how it maps to production

| Role | Production | Here |
|---|---|---|
| "Host" pm + host engine | the user's host | this impl container (its own rootless engine) |
| Cache entry preparation | prep container launched from the host | prep container launched from this container |
| Scenario/impl containers (cache consumers) | containers the host pm launches | `pm-qual-*-s1/-s2`, created by pm's own `create_qa_container` |
| Nested pm launch | test project's pm inside a scenario | pm (`create_container`) inside worker 1 |

Everything here sits one nesting level deeper than in production, with two
consequences:

* Engines in a container launched from a container could not start at all
  (`newuidmap: write to uid_map failed`).  That was a real defect, fixed by
  the subuid fit pm now runs in every nested-podman container (spec §1
  fact 7).  On the host topology the fit is a no-op (unit-tested against the
  host-launched uid_map).
* At this depth the consumers' root filesystem is fuse-overlayfs, where
  podman cannot mount containers (spec §1 fact 8).  So the workers' engines
  ran with `HOME=/scratch/eng` (`pm container engine-setup`) instead of
  the default `/home/pm` engine.  Host-launched consumers have a native
  overlay rootfs, where the default engine works (as podman does in this
  impl container).  The default engine's config is written by
  `create_container` either way (verified in worker 1:
  `~/.config/containers/storage.conf` present, image visible `R/O=true`).

Image under test: `localhost/pm-dev:latest` built from this branch's
Dockerfile — ID `536fa9300ee9…`, 14 layers, 1.89 GB reported.

## 1. One pinned image shared by two concurrent workers and a nested pm launch

**Cold preparation (once per image version)** — `A-cold-prep.json`

| | |
|---|---|
| wall time, `ensure_prepared` cold | 136.5 s (prep container + save→load stream 123.7 s) |
| `podman save` stream read from the host store | 1,885,386,240 B (not written to disk) |
| shared store, allocated (`du`) | 1,938,530,304 B (one copy of the 14 layers) |
| network during prep | rx 50 KB / tx 105 KB (no image download) |
| disk written, host-wide counter | 8.7 GB over 136 s — includes other tenants' I/O and `podman load`'s temporary copy of the stream inside the prep container (transient, deleted with it) |

**Warm** — `ensure_prepared` 0.47–0.56 s (one `image inspect`); network
432 B; no prep container started.

**Two isolated workers launched concurrently** — `B-E-workers-*.json`

| | worker 1 | worker 2 |
|---|---|---|
| `create_qa_container` (concurrent) | 5.6 s | 6.0 s |
| image seen by the engine | `localhost/pm-dev:latest 536fa9300ee9 R/O=true` | same |
| warm start of a workload container (concurrent) | 1.97 s | 1.93 s |
| private graphroot after writing a marker + 8/16 MB | 8,605,696 B | 16,994,304 B |

Network during the concurrent creates: 1.8 KB; during the concurrent warm
starts: 648 B.  No pull, load, build or layer copy happened: the shared
store's tree digest (`find` of names, sizes, mtimes, owners, modes) is
identical before the workers, after them and after the nested launch
(`8f6ebf31…`, 1,938,542,592 B).

**Nested pm launch** — pm's `create_container` run inside worker 1 for a
test project with `nested_podman: true` and a private `HOME=/scratch/npm`
(consumer mode):

* 6.74 s, container ready (setup sentinel present), image ID `536fa9300ee9…`
  (`R/O=true`); the engine config for the private HOME was written
  automatically; nothing built, pulled or imported.
* the launched container has **no** `/var/lib/pm-image-cache` (the entry is
  not passed one keep-id level deeper — spec A3).
* private bytes of that engine with three containers from the image (pm's
  keep-id launch, a second keep-id container, a default-userns container):
  **446,464 B** (`D-nested-du.txt`).  (The JSON's 1.93 GB figure walked the
  running containers' mounted `merged/` rootfs; `du -x` excludes it.)

## 2. Writes are private; mounts read-only; mappings verified

* Each worker's marker (`/etc/qual-marker`, written as root over a
  lower-layer directory) is visible only in its own container; neither
  worker's graphroot contains the other's marker.
* Writing into the shared store fails from the engine user and from
  `podman unshare` root: `Read-only file system`; mountinfo shows
  `/var/lib/pm-image-cache ro,relatime`.
* Store digest unchanged throughout (above).
* UID/GID: probes read `uid0 0:0`, `uid1 1:1` through `podman unshare
  stat`; inside the workload `id -u` = 1000, `/home/pm` is `pm:pm`,
  `/usr/bin/newuidmap` `root:root` (image ownership intact).  Worker
  uid_map `0 1 999 / 999 1000 1 / 1000 0 1 / 1001 1001 64534`, fitted
  `/etc/subuid` `pm:1:998, pm:999:1, pm:1001:64534`.
* Worker mounts (`podman inspect`): workdir, scratch, pm source (ro),
  claude binary (ro), `~/.claude`, hooks, and the cache entry (`rw=False`).
  No podman socket, no host graphroot.  Label `pm.image-cache=536fa9300ee9c413b9e4`.
* `pm container cache check` passes all seven checks in both workers.

## 3. Failure modes are actionable, with no fallback

Bounded fixtures (`H-failures.json`); real runtime unless noted.

| Case | Result |
|---|---|
| H1 preparation fails (image without podman: `ubuntu:22.04`) | `ContainerError` after 19 s: "the shared image cache … is unavailable. Cause: … (save rc=141, load rc=127): executable file `podman` not found … To retry: … 'pm container cache prepare' … 'pm set container-image-cache off'". No consumer container, no prep container, no partial entry left; a stale `.prep-*` dir and prep container from a previously killed preparer were cleared under the lock. |
| H2 incompatible entry (store + probes prepared one keep-id level above the consumers) | `pm container cache check` FAIL: "uid1 is 65534:65534, expected 1:1 … prepared for engines at another nesting level". Nested pm launch: `ContainerError` "…prepared for engines at another user-namespace level (probes read 0:0 65534:65534 …) … cannot serve this engine". Nothing launched. |
| H3 overlay support missing (consumer without `/dev/fuse`) | check FAIL and nested launch `ContainerError`: "overlay support is unavailable in this container (/dev/fuse missing) … pm does not fall back to VFS". |
| H4 image not in the cache (nested pm configured for `localhost/pm-other:1`) | `ContainerError` naming the cached image and the remedies; afterwards the engine holds only the shared `pm-dev` (`R/O=true`) and no containers — nothing was built, pulled or imported. |
| Cache root / scratch on network storage | refused with the setting to change (unit tests with an NFS/CIFS mount table; `pm set image-cache-dir|scratch-dir` refuse too). |
| Mode `off` | today's behaviour, by explicit choice only (unit test). |

pm never selects VFS and never launches on the host in any of these paths;
container-mode failures stay `ContainerError` (the fail-closed boundary
pr-cd04629 centralises).

## 4. Disk

Allocated bytes (`du`, `-x` where a store could have live mounts):

| | bytes |
|---|---|
| shared entry for `pm-dev:latest` (all 14 layers, once per image version) | 1,938,542,592 |
| **VFS store of the same image** (what a VFS fixture paid per engine; `F-G-disk.txt`, loaded in 157 s) | **16,934,260,736** |
| worker 1 private graphroot (workload + marker + 8 MB) | 8,605,696 |
| worker 2 private graphroot (workload + marker + 16 MB) | 16,994,304 |
| nested pm engine, three containers (two keep-id) | 446,464 |
| worker 2 after a `FROM localhost/pm-dev` build fixture adding a 16 MB layer (93 s) | 33,882,112 (+16.9 MB build) |

So an ordinary ~1.9 GB image no longer costs ~17 GB per scenario engine:
the image is stored once (1.94 GB) and each engine holds only its private
changes (here 0.4–34 MB).  Transient writes remain: the cold preparation
streams the image through `podman load`, which stages it in the prep
container before unpacking (removed with the prep container); builds and
workloads write what they write.  The host-wide disk counter during the
cold preparation (8.7 GB in 136 s) also includes other tenants' I/O on the
shared host disk, so it is an upper bound, not this PR's cost.

## 5. Cleanup and path separation

**Reclaim** (`I-reclaim.txt`, `pm container reclaim --pr pr-qual`):

1. Both workers running: dry run plans only an earlier, ended run's two
   stores (208 KiB + 204 KiB) and keeps both live scratch dirs ("a container
   still mounts …").
2. Worker 1's container removed, worker 2 still running: removed worker 1's
   engine store (11.1 MiB), the nested pm engine's store (452 KiB) and an
   image export `tiny-export.tar` (2.9 MiB), plus the earlier run's stores;
   kept `draft.md`, engine configs, the nested test project and the checkout
   (`~/.pm/workdirs/qa/<run>/s-1/repo`); wrote `.pm-reclaim.json`.  Worker 2
   held.
3. Worker 2 removed: its store (32.3 MiB) reclaimed.

The same function runs from `pr_cleanup.cleanup_pr_resources` (merged /
closed PRs, `pm pr cleanup --resources`) and in the background at QA run
start for earlier runs of the PR (unit-tested).  Cache entries are evicted
only when no container (any state) carries their label and their image is
gone from the host or superseded — left untagged by a rebuild of its tag
(unit-tested; `pm container cache gc`; that podman 3.4 keeps the old image
untagged after a same-tag rebuild was checked with a small `FROM scratch`
build, review 62b4 i6).

**Source / evidence vs local paths** — scenario scratch now lives under
`~/.pm/scratch/qa/<run>/s-N` while the checkout stays under the workdir
root; `workdirs-dir` and `captures-dir` may point at network storage,
`scratch-dir` and `image-cache-dir` are refused there (unit tests with
simulated `nfs4`/`cifs` mounts; `pm set` refuses too).

**NAS: qualification outstanding.**  No NAS is mounted in this container,
so Git and container access on a real NAS-backed checkout/evidence dir has
not been exercised.  To finish it on the host: `pm set workdirs-dir
<nas>/pm-workdirs`, `pm set captures-dir <nas>/pm-captures`, run one QA
scenario with a nested engine, and check that the scenario's checkout and
captures are on the NAS while `/scratch` and the engine graphroot are on
local disk (`stat -f`), plus `git push` through the proxy from the NAS
checkout.

## Not covered here

* Engines one keep-id level below a consumer (containers launched by a
  nested pm) get no shared cache — by design (spec A3).
* The default `/home/pm` engine of a *host-launched* consumer was not run
  from here (this topology is one level deeper; see above).  It is the same
  engine config, on a native-overlay rootfs like this impl container's.
