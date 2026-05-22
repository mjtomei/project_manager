FROM ubuntu:22.04

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
# Ensure the pm user's ~/.local/bin (where the git push-proxy wrapper is
# installed at container startup) is on PATH for non-login shells —
# ``docker exec bash -c`` doesn't source profile files.
ENV PATH=/home/pm/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Make pm's source tree (bind-mounted at /opt/pm-src by container.py)
# importable without a per-container pip install.  The /usr/local/bin/pm
# shim below runs ``python3 -m pm_core.wrapper`` which picks up pm_core
# from here (or from a local ./pm_core in cwd via the wrapper's local-win
# logic, for pm-on-pm PRs).
ENV PYTHONPATH=/opt/pm-src

# Install essential developer tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    jq \
    python3 \
    python3-pip \
    python3-venv \
    ca-certificates \
    gnupg \
    podman \
    fuse-overlayfs \
    slirp4netns \
    uidmap \
    libcap2-bin \
    tmux \
    sudo \
    asciinema \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Nested rootless podman: replace setuid bit on newuidmap/newgidmap with
# file capabilities. Setuid in a nested user namespace gets bounded by the
# namespace owner; file caps are evaluated within the namespace and grant
# CAP_SETUID/CAP_SETGID to the caller correctly. Without this, an inner
# rootless podman fails with "newuidmap: write to uid_map failed: Operation
# not permitted" even though /etc/subuid permits the mapping.
RUN chmod u-s /usr/bin/newuidmap /usr/bin/newgidmap && \
    setcap cap_setuid+ep /usr/bin/newuidmap && \
    setcap cap_setgid+ep /usr/bin/newgidmap

# Pre-create the pm user (UID 1000) so /etc/subuid below can reference it
# by name. container.py's runtime ``useradd`` is idempotent (|| true) so
# existing-user errors are swallowed when host UID also happens to be 1000.
RUN groupadd -g 1000 pm && useradd -m -u 1000 -g 1000 -s /bin/bash pm \
    && echo 'pm ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/pm \
    && chmod 0440 /etc/sudoers.d/pm

# Constrain pm's subuid/subgid range to what fits inside the *inner*
# (outer-container's) user namespace. The outer namespace is 65536 wide
# (from the host user's /etc/subuid entry, e.g. matt:100000:65536), so
# inner UIDs 0-65536 exist. The default useradd entry "pm:100000:65536"
# (added by Ubuntu's adduser defaults) claims UIDs that don't exist in
# the inner namespace and the kernel rejects newuidmap writes against
# them. Restrict to "pm:1:999,pm:1001:64535" — within range, skipping
# pm's own UID 1000.
RUN printf 'pm:1:999\npm:1001:64535\n' > /etc/subuid && \
    printf 'pm:1:999\npm:1001:64535\n' > /etc/subgid

# Configure Podman for nested container use. Use overlay + fuse-overlayfs
# (requires --device /dev/fuse on the outer container, gated by the
# project-level nested_podman setting in pm_core/container.py).
RUN mkdir -p /etc/containers && \
    printf '[storage]\ndriver = "overlay"\n[storage.options.overlay]\nmount_program = "/usr/bin/fuse-overlayfs"\n' > /etc/containers/storage.conf && \
    printf '[containers]\nnetns = "host"\n' > /etc/containers/containers.conf

# Install Node.js 22.x LTS via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Verify installations
RUN git --version && python3 --version && pip3 --version \
    && node --version && npm --version && curl --version | head -1 \
    && jq --version && gcc --version | head -1 \
    && ffmpeg -version | head -1

# --- Playwright + Chromium (browser QA recording) ---
# Pre-install Playwright (Node) and its bundled Chromium so the walker-UI QA
# PRs can record rendered browser video/traces.  Chromium only — Firefox and
# WebKit are skipped to limit image size.  NOTE: this adds several hundred MB
# to the image (Chromium ~300MB + Playwright deps); accepted to keep a single
# base image with no per-project split.
#
# Browsers install to PLAYWRIGHT_BROWSERS_PATH (a fixed non-home path) rather
# than ~/.cache/ms-playwright: this RUN executes as root (USER pm is set
# below, and `--with-deps` apt installs need root), so a home-relative cache
# would land in /root and be invisible to the runtime `pm` user.  The ENV
# persists into the runtime layer and `chmod -R a+rx` lets `pm` launch the
# browser.  NODE_PATH points at the global npm dir so `require('playwright')`
# resolves from node scripts the `pm` user runs.
#
# Runtime contract for callers: launch Chromium with
#   chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })
# inside the rootless container.  `--no-sandbox` disables Chromium's
# user-namespace sandbox (unavailable rootless / when running as root) and
# `--disable-dev-shm-usage` makes Chromium use /tmp instead of the small
# default /dev/shm — together these mean no `podman run` flag/mount
# (--shm-size, --cap-add, seccomp) is required, so pm_core/container.py is
# unchanged.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
ENV NODE_PATH=/usr/lib/node_modules
RUN npm install -g playwright \
    && npx playwright install --with-deps chromium \
    && chmod -R a+rx "$PLAYWRIGHT_BROWSERS_PATH" \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

# Verify Playwright + Chromium: CLI version, module require, and a headless
# Chromium smoke launch with the container-safe flags (about:blank → dump
# DOM).  Fails the build if Chromium can't start in the container.  (ffmpeg
# is verified above with the other apt tools.)
RUN npx playwright --version \
    && node -e "require('playwright')" \
    && node -e "const {chromium}=require('playwright');(async()=>{const b=await chromium.launch({args:['--no-sandbox','--disable-dev-shm-usage']});const p=await b.newPage();await p.goto('about:blank');console.log('chromium-smoke-dom:',await p.content());await b.close();})().catch(e=>{console.error(e);process.exit(1)})"

# Pre-install pm's runtime Python deps system-wide so ``import pm_core``
# (via the /usr/local/bin/pm shim below + PYTHONPATH=/opt/pm-src) works
# without a per-container install step.  Keep this list in sync with
# ``[project.dependencies]`` in pyproject.toml.
RUN pip3 install \
    'click>=8.0' 'pyyaml>=6.0' 'textual>=0.40' 'pyperclip>=1.8'

# pm shim: invoke the wrapper with the system python, which finds pm_core
# via PYTHONPATH.  No venv, no per-container install — the bind-mounted
# source at /opt/pm-src is the single source of truth.
RUN printf '#!/bin/sh\nexec python3 -m pm_core.wrapper "$@"\n' > /usr/local/bin/pm \
    && chmod 755 /usr/local/bin/pm

# Git identity baked from host git config at base-build time. Both env
# vars (for tools that read GIT_AUTHOR_*/GIT_COMMITTER_*) and a system-wide
# /etc/gitconfig (for tools that query `git config`) so any user inside the
# container — pm or otherwise — gets a usable identity.
ARG GIT_USER_NAME=""
ARG GIT_USER_EMAIL=""
ENV GIT_AUTHOR_NAME="${GIT_USER_NAME}" \
    GIT_AUTHOR_EMAIL="${GIT_USER_EMAIL}" \
    GIT_COMMITTER_NAME="${GIT_USER_NAME}" \
    GIT_COMMITTER_EMAIL="${GIT_USER_EMAIL}"
RUN if [ -n "$GIT_USER_NAME" ]; then \
        git config --system user.name "$GIT_USER_NAME"; \
    fi \
    && if [ -n "$GIT_USER_EMAIL" ]; then \
        git config --system user.email "$GIT_USER_EMAIL"; \
    fi

USER pm
WORKDIR /home/pm
