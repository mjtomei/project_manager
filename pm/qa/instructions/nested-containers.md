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
existing `storage.conf` or `containers.conf` it did not write; the error
says what to add to that file, and `--force` replaces it instead. After
editing such a file yourself, verify it with `HOME=<engine home> pm
container cache check` (`engine-setup` keeps refusing a file it did not
write).

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
    printf 'FROM localhost/pm-dev:latest\nUSER root\nRUN echo fixture > /etc/pm-fixture\n' > Containerfile
    podman build --uts host -t localhost/pm-fixture:test .

pm-dev ends with `USER pm`, so a `RUN` step that writes outside `/home/pm`
needs `USER root` first (without it: `Permission denied`). New layers land
in your private graphroot; the base layers stay shared. The `COMMIT` step
takes a minute or two: it diffs the new layer against the shared base.
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
