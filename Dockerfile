FROM ubuntu:22.04

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
# Ensure the pm user's ~/.local/bin (where pm and the git push-proxy
# wrapper are installed at container startup) is on PATH for non-login
# shells — ``docker exec bash -c`` doesn't source profile files.
ENV PATH=/home/pm/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

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
    && rm -rf /var/lib/apt/lists/*

# Configure Podman for nested container use (vfs driver avoids needing
# /dev/fuse, which would require --device or --privileged on the outer
# container).
RUN mkdir -p /etc/containers && \
    printf '[storage]\ndriver = "vfs"\n' > /etc/containers/storage.conf && \
    printf '[containers]\nnetns = "host"\n' > /etc/containers/containers.conf

# Install Node.js 22.x LTS via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Verify installations
RUN git --version && python3 --version && pip3 --version \
    && node --version && npm --version && curl --version | head -1 \
    && jq --version && gcc --version | head -1

# Pre-install pm's runtime Python deps system-wide.  At container startup
# pm is installed from /opt/pm-src with --no-deps into the pm user's
# ~/.local, so deps must already be importable here.  Keep this list in
# sync with ``[project.dependencies]`` in pyproject.toml.
RUN pip3 install \
    'click>=8.0' 'pyyaml>=6.0' 'textual>=0.40' 'pyperclip>=1.8'
