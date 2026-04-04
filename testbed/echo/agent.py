"""Run the echo agent against the testbed config."""

import sys
from pathlib import Path

# Ensure repo root is on sys.path so examples/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from examples.echo_agent import EchoAgent

bot = EchoAgent.from_config(
    str(Path(__file__).resolve().parent / "agent.yaml")
)
bot.run()
