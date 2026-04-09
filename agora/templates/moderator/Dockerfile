FROM python:3.12-slim

# Install agora from local source
COPY agora/ /tmp/agora-src/agora/
COPY pyproject.toml /tmp/agora-src/
RUN pip install /tmp/agora-src/ && rm -rf /tmp/agora-src/

# Create non-root user
RUN useradd -m -s /bin/bash agent

WORKDIR /agent
COPY fleet/{{name}}/ .
RUN chown -R agent:agent /agent

USER agent

CMD ["python", "agent.py"]
