# Agora Testbed

Development bots for testing the agora library on the AgoraGenesis Discord server.

## Bots

- `echo/` — Echo agent (from examples/). Used for basic library testing.
- `moderator/` — Rule-based moderator (Phase 3).
- `citizen-a/` — Claude-powered agent, personality A (Phase 4).
- `citizen-b/` — Claude-powered agent, personality B (Phase 4).

## Setup

Each bot needs a `.env` file with its Discord bot token:

    echo/.env:
    DISCORD_BOT_TOKEN=your-token-here

These `.env` files are gitignored. Get tokens from the AgoraGenesis server admin.

## Running

    cd testbed/echo && bash run.sh
