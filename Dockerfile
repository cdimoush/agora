FROM python:3.12-slim

# System deps: git, gh CLI, Claude Code
RUN apt-get update && apt-get install -y curl git && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && apt-get install -y gh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Pre-install agora dependencies (editable install happens at startup from mount)
COPY pyproject.toml /tmp/agora-src/
COPY agora/ /tmp/agora-src/agora/
RUN pip install /tmp/agora-src/ && rm -rf /tmp/agora-src/ && pip uninstall -y agora

# Non-root user
RUN useradd -m -u 1000 -s /bin/bash agent

# Git config
RUN git config --global --add safe.directory /home/agent/agora && \
    git config --global credential.https://github.com.helper "" && \
    git config --global credential.https://github.com.helper "!/usr/bin/gh auth git-credential"

RUN mkdir -p /home/agent/.claude && chown agent:agent /home/agent/.claude

# Entrypoint — copied in, everything else comes from mount
COPY agent/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER agent
WORKDIR /home/agent

ENTRYPOINT ["entrypoint.sh"]
