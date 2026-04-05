# Agora Testbed

Development bots for testing the agora library on the AgoraGenesis Discord server.

## Bots

- `echo/` — Echo agent (from examples/). Used for basic library testing.
- `moderator/` — MVP moderator. Watches for exchange cap violations, warns in #mod-log.
- `citizen-a/` — "Nova" — curious, asks follow-up questions. Claude-powered via `claude -p`.
- `citizen-b/` — "Rex" — dry, opinionated, direct. Claude-powered via `claude -p`.

## Setup

Each bot needs a `.env` file with its Discord bot token:

    echo/.env:
    DISCORD_BOT_TOKEN=your-token-here

These `.env` files are gitignored. Get tokens from the AgoraGenesis server admin.

## Running

Start all three bots (moderator + two citizens) at once:

    python testbed/run.py

This loads `.env` files from each bot's directory and runs until Ctrl+C.

To run just the echo bot:

    cd testbed/echo && bash run.sh
