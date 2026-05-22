# Spec: Container — pre-install Playwright + Chromium + ffmpeg for browser QA recordings

PR: pr-37073ad · Plan: plan-litreview (plan-3119574) · Branch:
`pm/pr-37073ad-container-pre-install-headless-chrome-ffmpeg-puppe`

## Context grounded in the codebase

- The QA container image is built from a single bundled `Dockerfile`
  (`FROM ubuntu:22.04`). `pm_core/container.py:build_image()` runs
  `<runtime> build -t pm-dev:latest -f Dockerfile .` with `GIT_USER_NAME` /
  `GIT_USER_EMAIL` build args; `DEFAULT_IMAGE = "pm-dev:latest"`.
  `create_container()` auto-builds the image on first use if absent.
- Existing QA-recording tooling already in the `Dockerfile`: `asciinema`,
  `tmux`, `curl` (apt list at lines 17–35) — terminal/protocol capture only,
  no browser engine. Node.js 22.x is installed via NodeSource (lines 72–75)
  and verified (lines 78–80). The image switches to `USER pm` (UID 1000) at
  line 112; everything before that runs as root.
- Runtime container args are assembled in `create_container()` (around
  line 575+). Rootless podman uses `--userns=keep-id`; `nested_podman`
  projects add `--device /dev/fuse`, `--device /dev/net/tun`,
  `--security-opt unmask=ALL` via `_nested_podman_run_args()`. No
  `--shm-size` is currently passed.
- The walker-UI QA PRs that consume this image are pr-ac58803 (artifact
  recipe) and pr-5db0e85 (rendered snapshot path). Both launch Chromium with
  `chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })`
  (plan-3119574 lines 205, 213). Those flags are passed by the *caller* to
  Playwright, not to `podman run`.

## 1. Requirements (grounded)

R1. **Install the `playwright` npm package** (Node 22 already present) at the
    root layer of `Dockerfile`, before `USER pm`. Make it resolvable both as
    a CLI (`npx playwright`) and via `require('playwright')` from arbitrary
    node scripts run by the `pm` user at runtime.

R2. **Install bundled Chromium + system deps** via
    `npx playwright install --with-deps chromium`. `--with-deps` runs
    `apt-get` for Chromium's runtime shared libs (libnss3, libatk-bridge2.0-0,
    libgtk-3-0, libgbm1, libasound2, fonts, …), so we do **not** hand-maintain
    that apt list. Chromium only — no Firefox/WebKit.

R3. **Install `ffmpeg`** via apt (added to the existing apt block at the top
    so all apt packages stay together). Needed for `.webm`→`.mp4` transcode
    and the existing asciinema workflow; Playwright bundles its own ffmpeg for
    recording so this is supplementary.

R4. **Build-time verification step** (new `RUN`, mirroring the existing node
    verify at lines 78–80): `npx playwright --version` exits 0; a headless
    Chromium smoke script (`chromium.launch({args:['--no-sandbox',
    '--disable-dev-shm-usage']})` → `page.goto('about:blank')` → dump DOM)
    exits 0; `ffmpeg -version` exits 0; `node -e "require('playwright')"`
    succeeds.

R5. **Existing tooling preserved** — asciinema, tmux, curl, node, podman,
    pip deps, the `pm` shim, git identity all remain. (Pure additive change.)

R6. **`pm_core/container.py`** is touched **only if** a runtime flag/mount is
    actually required for Chromium. See Ambiguity A1 → resolved: no change
    required.

R7. **Flag the image-size increase** (Chromium + Playwright is heavy) in a
    `Dockerfile` comment and in the PR notes.

## 2. Implicit requirements

- **Shared browser location.** `--with-deps` and the apt step require root, so
  the install runs before `USER pm`. By default Playwright downloads browsers
  to `$HOME/.cache/ms-playwright`; installed as root that is `/root/.cache`,
  which the `pm` user cannot find at runtime. Resolution: set
  `ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright` (a fixed, non-home path)
  **before** the install so browsers land there, and `chmod -R a+rx` the tree
  so the `pm` user can read/execute them. The ENV persists into the runtime
  layer, so the `pm` user resolves the same path.
- **`require('playwright')` resolution.** A global npm install
  (`npm install -g playwright`) puts the package in `npm root -g`
  (`/usr/lib/node_modules` on NodeSource node 22). Node's `require` does not
  search the global dir by default, so set `ENV NODE_PATH=/usr/lib/node_modules`
  for `node -e "require('playwright')"` to succeed at build and runtime. The
  global install also creates the `playwright` CLI on PATH so `npx playwright`
  resolves it without a network fetch.
- **Running Chromium as root at build time** requires `--no-sandbox` (Chromium
  refuses the setuid sandbox as root) — already in the smoke-test launch args.
- **No new network ports / mounts**; the captures bind-mount already exists for
  QA workers to write recordings.

## 3. Ambiguities (resolved)

A1. *Does Chromium in the rootless container need a `podman run` flag/mount
    (e.g. `--shm-size`, `--device`, seccomp)?* **Resolved: no.**
    - `--disable-dev-shm-usage` (passed by callers to `chromium.launch`) tells
      Chromium to write shared memory to `/tmp` instead of the default 64 MB
      `/dev/shm`, which is exactly why callers pass it — it removes the only
      reason to add `podman --shm-size`.
    - `--no-sandbox` (also caller-side) disables Chromium's user-namespace
      sandbox, so no `--cap-add`/seccomp relaxation is needed.
    - Therefore `pm_core/container.py` is **not modified**. The runtime
      contract (callers must launch with both flags) is documented in a
      `Dockerfile` comment so it is discoverable from the image definition.

A2. *Pin the Playwright version?* The existing `Dockerfile` does not pin node's
    minor (`setup_22.x` → latest) or apt package versions; matching that
    convention, install **latest** `playwright`. The just-installed package's
    own `install` subcommand downloads the matching Chromium build, so package
    and browser are always in lockstep. (Noted as a reproducibility trade-off.)

A3. *Run the smoke test as root or as `pm`?* Run it at build time as root
    (the build's active user before `USER pm`). The `chmod -R a+rx` on the
    browser tree plus the persisted `PLAYWRIGHT_BROWSERS_PATH`/`NODE_PATH`
    ENVs guarantee the `pm` user can launch identically at runtime; a root
    build-time launch with `--no-sandbox` is the representative smoke check the
    task asks for ("verified by build + smoke-launch").

## 4. Edge cases / interactions

- **Image-size increase**: Chromium + Playwright add several hundred MB. Flagged
  in a Dockerfile comment and PR notes; acceptable per the task (single base
  image, no multi-image split).
- **`--with-deps` re-runs `apt-get update`**: fine; the layer ends without a
  matching `rm -rf /var/lib/apt/lists/*` from Playwright, so add an explicit
  cleanup to keep the layer lean, consistent with the existing apt blocks.
- **Nested-podman builds**: unaffected — the Playwright layer does no
  `sethostname`/cgroup work, so the `--uts host` build accommodation
  (memory: container_qa_loop_full_traversal) is not needered here.
- **No human-guided testing**: verification is entirely the build + smoke step.

## 5. Plan

1. `Dockerfile`: add `ffmpeg` to the apt block (R3).
2. `Dockerfile`: new root-layer section after the Node install (R1, R2, +
   implicit): set `PLAYWRIGHT_BROWSERS_PATH` + `NODE_PATH` ENVs,
   `npm install -g playwright`, `npx playwright install --with-deps chromium`,
   `chmod -R a+rx` the browser tree, clean apt lists, with a size + runtime-flag
   comment (R7, A1 doc).
3. `Dockerfile`: build-time verify `RUN` (R4).
4. Verify with a real `podman build`.
5. No `pm_core/container.py` change (A1).
