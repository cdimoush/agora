FROM python:3.12-slim

# Install agora from local source
COPY agora-src/ /tmp/agora-src/
RUN pip install /tmp/agora-src/ && rm -rf /tmp/agora-src/

# Create non-root user
RUN useradd -m -s /bin/bash agent

WORKDIR /agent
COPY agent/ .
RUN chown -R agent:agent /agent

USER agent

CMD ["python", "agent.py"]
