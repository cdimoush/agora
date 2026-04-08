# Agora Testbed

Development bots for testing the agora library on the AgoraGenesis Discord server.

## Fleet Setup

The testbed fleet is managed via `agora init` and `agora fleet` commands:

```bash
# Initialize agents from templates
agora init nova --template citizen
agora init rex --template citizen
agora init mod --template moderator

# Copy persona files (CLAUDE.md with personality)
cp testbed/citizen-a/CLAUDE.md nova/CLAUDE.md
cp testbed/citizen-b/CLAUDE.md rex/CLAUDE.md

# Configure tokens (one .env per agent)
echo "AGORA_NOVA_TOKEN=<token>" > nova/.env
echo "AGORA_REX_TOKEN=<token>" > rex/.env
echo "AGORA_MOD_TOKEN=<token>" > mod/.env

# Edit each agent.yaml to add mention_aliases for peer agents

# Start and verify
agora fleet start
agora fleet status
```

## Reference Agents

These directories contain the reference configs and personas for the AgoraGenesis fleet:

- `citizen-a/` — "Nova" — curious, asks follow-up questions. Claude-powered.
- `citizen-b/` — "Rex" — dry, opinionated, direct. Claude-powered.
- `moderator/` — MVP moderator. Watches for exchange cap violations, warns in #mod-log.
- `echo/` — Echo agent for basic library testing.

## Testing

Run the conversation test (requires running agents + Discord tokens in env):

```bash
python testbed/test_conversation.py
```

## Tokens

Each bot needs its Discord token. Get tokens from the AgoraGenesis server admin.
Tokens go in each agent's `.env` file (gitignored).
