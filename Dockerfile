FROM python:3.12-slim

# System deps: Node.js, git, gh CLI, Claude CLI
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

# Beads CLI (compiled against ICU 74; container may have newer ICU)
COPY bd /usr/local/bin/bd
RUN chmod +x /usr/local/bin/bd && \
    ICU_VER=$(ls /usr/lib/x86_64-linux-gnu/libicuuc.so.* 2>/dev/null | head -1 | grep -oP '\d+$') && \
    if [ -n "$ICU_VER" ] && [ "$ICU_VER" != "74" ]; then \
      ln -sf /usr/lib/x86_64-linux-gnu/libicui18n.so.$ICU_VER /usr/lib/x86_64-linux-gnu/libicui18n.so.74 && \
      ln -sf /usr/lib/x86_64-linux-gnu/libicuuc.so.$ICU_VER /usr/lib/x86_64-linux-gnu/libicuuc.so.74 && \
      ln -sf /usr/lib/x86_64-linux-gnu/libicudata.so.$ICU_VER /usr/lib/x86_64-linux-gnu/libicudata.so.74; \
    fi

# Install agora library dependencies (editable install happens at startup from worktree)
COPY pyproject.toml /tmp/agora-src/
COPY agora/ /tmp/agora-src/agora/
RUN pip install /tmp/agora-src/ && rm -rf /tmp/agora-src/ && pip uninstall -y agora

# Non-root user
RUN useradd -m -u 1000 -s /bin/bash agent

# Git config
RUN git config --global user.name "agora-dev" && \
    git config --global user.email "dev@agora.local" && \
    git config --global --add safe.directory /workspace/agora && \
    git config --global credential.https://github.com.helper "" && \
    git config --global credential.https://github.com.helper "!/usr/bin/gh auth git-credential"

RUN mkdir -p /home/agent/.claude && chown agent:agent /home/agent/.claude

# Copy agent code (everything except what's in .dockerignore)
WORKDIR /agent
COPY agent.py mind.py agent.yaml CLAUDE.md ./
COPY entrypoint.sh /agent/entrypoint.sh
RUN chmod +x /agent/entrypoint.sh && chown -R agent:agent /agent

USER agent

ENTRYPOINT ["/agent/entrypoint.sh"]
