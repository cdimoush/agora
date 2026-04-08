FROM python:3.12-slim

# Install agora from local source
COPY agora-src/ /tmp/agora-src/
RUN pip install /tmp/agora-src/ && rm -rf /tmp/agora-src/

# Install Node.js and Claude CLI
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash agent

WORKDIR /agent
COPY agent/ .
RUN chown -R agent:agent /agent

USER agent

CMD ["python", "agent.py"]
