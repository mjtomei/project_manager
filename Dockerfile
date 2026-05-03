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
RUN groupadd -g 1000 pm && useradd -m -u 1000 -g 1000 -s /bin/bash pm

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
    && jq --version && gcc --version | head -1

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
