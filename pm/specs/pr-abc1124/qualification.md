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

(filled from `H-failures.json`)

## 4. Disk

(filled from `F-G-disk.txt`)

## 5. Cleanup and path separation

(filled from `I-reclaim.txt`)
