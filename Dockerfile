FROM python:3.12-slim

# System deps: git, gh CLI, Claude Code, ICU (for beads/dolt)
RUN apt-get update && apt-get install -y curl git libicu-dev && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && apt-get install -y gh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Beads CLI (embedded dolt, needs ICU 74 symlinks if container has newer ICU)
COPY bd /usr/local/bin/bd
RUN chmod +x /usr/local/bin/bd && \
    ICU_VER=$(ls /usr/lib/x86_64-linux-gnu/libicuuc.so.* 2>/dev/null | head -1 | grep -oP '\d+$') && \
    if [ -n "$ICU_VER" ] && [ "$ICU_VER" != "74" ]; then \
      ln -sf /usr/lib/x86_64-linux-gnu/libicui18n.so.$ICU_VER /usr/lib/x86_64-linux-gnu/libicui18n.so.74 && \
      ln -sf /usr/lib/x86_64-linux-gnu/libicuuc.so.$ICU_VER /usr/lib/x86_64-linux-gnu/libicuuc.so.74 && \
      ln -sf /usr/lib/x86_64-linux-gnu/libicudata.so.$ICU_VER /usr/lib/x86_64-linux-gnu/libicudata.so.74; \
    fi

# Pre-install agora dependencies (editable install happens at startup from mount)
COPY pyproject.toml /tmp/agora-src/
COPY agora/ /tmp/agora-src/agora/
RUN pip install /tmp/agora-src/ && rm -rf /tmp/agora-src/ && pip uninstall -y agora

# Non-root user
RUN useradd -m -u 1000 -s /bin/bash agent

# Git config
RUN git config --global --add safe.directory /home/agent && \
    git config --global credential.https://github.com.helper "" && \
    git config --global credential.https://github.com.helper "!/usr/bin/gh auth git-credential"

# Entrypoint — copied in, everything else comes from mount
COPY agent/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER agent
WORKDIR /home/agent

ENTRYPOINT ["entrypoint.sh"]
