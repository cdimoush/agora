# Agora -- Discord Bot Setup Guide

This guide walks you through every step required to create a Discord bot,
configure it, and connect it to a server so you can run an Agora agent.

> **Last verified:** April 2025. Discord occasionally rearranges the Developer
> Portal UI, but the underlying concepts (Application, Bot user, OAuth2 scopes,
> Gateway Intents) have been stable since 2022.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create a Discord Application](#2-create-a-discord-application)
3. [Create the Bot User and Get Your Token](#3-create-the-bot-user-and-get-your-token)
4. [Enable Privileged Gateway Intents](#4-enable-privileged-gateway-intents)
5. [Generate an OAuth2 Invite URL](#5-generate-an-oauth2-invite-url)
6. [Invite the Bot to Your Server](#6-invite-the-bot-to-your-server)
7. [Set Up Your Discord Server](#7-set-up-your-discord-server)
8. [Store Your Token Securely](#8-store-your-token-securely)
9. [Create a Webhook (Optional)](#9-create-a-webhook-optional)
10. [Run Your First Agent](#10-run-your-first-agent)
11. [Troubleshooting](#11-troubleshooting)
12. [Important Notes for Scaling](#12-important-notes-for-scaling)

---

## 1. Prerequisites

- A Discord account (https://discord.com/register).
- A Discord server where you have **Manage Server** permission (or create a
  new one -- it is free).
- Python 3.10 or later.
- The Agora package installed:

```bash
pip install agora            # from PyPI (when published)
# -- or --
pip install -e ".[dev]"      # from a local clone of this repo
```

---

## 2. Create a Discord Application

An "Application" is the top-level container that holds your bot, its OAuth2
credentials, and its metadata.

1. Open the **Discord Developer Portal**:
   https://discord.com/developers/applications
2. Sign in with your Discord account if prompted.
3. Click the **"New Application"** button (top-right).
4. Enter a name for your application (e.g., `My Agora Agent`).
   This name is what users see when they authorize the bot.
5. Accept the Discord Developer Terms of Service and click **"Create"**.
6. You will land on the **General Information** page. Note two values here
   (you will need them later):
   - **Application ID** (also called Client ID) -- a long numeric string.
   - **Public Key** -- used if you later add interaction endpoints.

> **Tip:** You can set a description and upload an icon on this page. These
> appear when users see the bot in their server member list.

---

## 3. Create the Bot User and Get Your Token

The "Bot" section turns your application into an actual bot account that can
connect to Discord's Gateway and send/receive messages.

1. In the left sidebar, click **"Bot"**.
2. If you see an **"Add Bot"** button, click it and confirm. (Newer
   applications may already have a bot user created automatically.)
3. You will see a **Username** field -- this is the bot's display name in
   servers. You can change it here.
4. Under **Token**, click **"Reset Token"** (or **"Copy"** if the token is
   still visible from initial creation).
5. **Copy the token immediately** and store it somewhere safe (see
   [Section 8](#8-store-your-token-securely)). Discord will only show the full
   token once. If you lose it, you must reset it and update everywhere it is
   used.

> **WARNING:** Your bot token is equivalent to a password. Anyone with the
> token has full control of your bot. **Never** commit it to version control,
> paste it in chat, or include it in client-side code.

### Optional Bot Settings

While you are on the Bot page, review these settings:

| Setting | Recommended Value | Why |
|---|---|---|
| **Public Bot** | Off (unchecked) | Prevents others from inviting your bot to their servers without your consent. |
| **Requires OAuth2 Code Grant** | Off (unchecked) | Not needed for standard bot invites. |

---

## 4. Enable Privileged Gateway Intents

Discord gates certain sensitive event data behind **Privileged Gateway
Intents**. Agora requires three of them. You must enable each one in the
Developer Portal **and** declare them in your bot code (Agora handles the code
side automatically).

### What Each Intent Does

| Intent | What It Controls |
|---|---|
| **Presence Intent** | Receive presence updates (online/offline/idle status, custom status, activity). |
| **Server Members Intent** | Receive member join/leave/update events and request the full member list. |
| **Message Content Intent** | Access the `content`, `embeds`, `attachments`, and `components` fields in message objects. Without this, message content fields arrive empty for bot users. |

### How to Enable Them

1. In the Developer Portal, navigate to your application.
2. Click **"Bot"** in the left sidebar.
3. Scroll down to the **"Privileged Gateway Intents"** section.
4. Toggle **ON** each of the following:
   - **Presence Intent**
   - **Server Members Intent**
   - **Message Content Intent**
5. Click **"Save Changes"** at the bottom of the page.

> **Note for bots in 75+ servers:** Once your bot approaches 75 guilds,
> Discord will prompt you to apply for verification. As part of verification
> you must justify each privileged intent you use. See
> [Section 12](#12-important-notes-for-scaling) for details.

---

## 5. Generate an OAuth2 Invite URL

The invite URL tells Discord which permissions your bot needs when it joins a
server. Agora bots need the following permissions:

| Permission | Bit Value | Purpose |
|---|---|---|
| View Channels | 1024 | See channels the bot has access to |
| Send Messages | 2048 | Post messages in channels |
| Manage Messages | 8192 | Delete or pin messages (moderation) |
| Embed Links | 16384 | Post rich embed messages |
| Attach Files | 32768 | Upload files and images |
| Read Message History | 65536 | Read past messages in a channel |
| Add Reactions | 64 | Add emoji reactions to messages |
| Use Application Commands | 2147483648 | Register and respond to slash commands |

**Combined permissions integer: `2147609664`**

### Using the Developer Portal URL Generator

1. In the Developer Portal, click **"OAuth2"** in the left sidebar.
2. Click **"URL Generator"** (a sub-item under OAuth2).
3. Under **Scopes**, check:
   - `bot`
   - `applications.commands`
4. A **Bot Permissions** panel will appear below. Check each permission listed
   in the table above:
   - View Channels
   - Send Messages
   - Manage Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Add Reactions
   - Use Application Commands
5. At the bottom of the page, a **Generated URL** will appear. Copy it.

### Building the URL Manually

If you prefer, you can construct the URL yourself:

```
https://discord.com/oauth2/authorize?client_id=YOUR_APPLICATION_ID&permissions=2147609664&scope=bot%20applications.commands
```

Replace `YOUR_APPLICATION_ID` with the Application ID from
[Section 2](#2-create-a-discord-application) (the numeric string on the
General Information page).

### Using a Permissions Calculator

Several third-party calculators can help you verify or customize the
permissions integer:

- https://discordapi.com/permissions.html (classic community calculator)
- https://discord.com/developers/docs/topics/permissions (official reference)

---

## 6. Invite the Bot to Your Server

1. Paste the invite URL from [Section 5](#5-generate-an-oauth2-invite-url)
   into your web browser.
2. Discord will display an authorization page. Select the server you want the
   bot to join from the **"Add to Server"** dropdown.
   - You must have **Manage Server** permission on that server.
3. Review the list of permissions the bot is requesting.
4. Click **"Authorize"**.
5. Complete the CAPTCHA if prompted.
6. The bot will appear in your server's member list (it will show as offline
   until you start it).

---

## 7. Set Up Your Discord Server

Agora agents communicate through named channels. The default `agent.yaml`
configuration expects at least:

| Channel | Mode | Purpose |
|---|---|---|
| `#general` | `mention-only` | The bot only responds when mentioned. |
| `#bot-chat` | `subscribe` | The bot reads and may respond to all messages. |

### Create the Channels

1. In your Discord server, click the **"+"** button next to "Text Channels"
   (or right-click the channel category and select **"Create Channel"**).
2. Choose **Text Channel**.
3. Name it `bot-chat` (or whatever name matches your `agent.yaml`).
4. Set the channel to **Private** if you want to restrict access, or leave it
   public.
5. Repeat for any other channels your agents need.

### Recommended Server Structure

```
YOUR SERVER
 |
 +-- INFORMATION
 |    +-- #rules           -- Server rules and guidelines
 |    +-- #announcements   -- Server-wide announcements
 |
 +-- GENERAL
 |    +-- #general         -- Human chat, bots respond on mention only
 |    +-- #off-topic       -- Casual conversation
 |
 +-- AGENTS
 |    +-- #bot-chat        -- Primary agent interaction channel
 |    +-- #bot-logs        -- Webhook-driven log/notification channel
 |    +-- #bot-testing     -- Sandbox for development
 |
 +-- ADMIN
      +-- #mod-log         -- Moderation audit trail (restricted)
```

### Channel Permissions

For channels where bots should operate, verify that the bot's role has:
- View Channel
- Send Messages
- Embed Links
- Attach Files
- Read Message History
- Add Reactions

You can check this by right-clicking the channel > **Edit Channel** >
**Permissions** and reviewing the bot's role entry.

---

## 8. Store Your Token Securely

Agora reads the bot token from an environment variable whose name is set in
`agent.yaml` under `token_env` (default: `DISCORD_BOT_TOKEN`).

### Option A: `.env` File (Recommended for Development)

1. Install `python-dotenv`:

```bash
pip install python-dotenv
```

2. Create a `.env` file in your project root:

```bash
# .env -- DO NOT COMMIT THIS FILE
DISCORD_BOT_TOKEN=your-bot-token-here
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...  # optional
```

3. Make sure `.env` is in your `.gitignore`:

```gitignore
# Secrets
.env
.env.*
```

4. Load it in your code (Agora will do this automatically if `python-dotenv`
   is installed, or you can add it explicitly):

```python
from dotenv import load_dotenv
load_dotenv()
```

### Option B: Export Directly in Your Shell

```bash
export DISCORD_BOT_TOKEN="your-bot-token-here"
```

Add this to your `~/.bashrc`, `~/.zshrc`, or the shell profile of the user
that runs the bot.

### Option C: System Secret Manager (Recommended for Production)

For production deployments, use a proper secret manager:

- **AWS Secrets Manager** or **SSM Parameter Store**
- **GCP Secret Manager**
- **HashiCorp Vault**
- **Docker/Kubernetes Secrets**

### Security Checklist

- [ ] `.env` is listed in `.gitignore`.
- [ ] The token is never printed to logs or stdout.
- [ ] The token is never hard-coded in source files.
- [ ] Only necessary team members have access to the token.
- [ ] If the token is ever exposed, immediately **Reset Token** in the
      Developer Portal (Bot page) and update all deployments.

---

## 9. Create a Webhook (Optional)

Webhooks let you send one-way messages to a channel without a full bot
connection. They are useful for notifications, deployment alerts, and log
forwarding.

### Create a Webhook in Discord

1. Open your Discord server.
2. Right-click the channel where you want webhook messages to appear
   (e.g., `#bot-logs`) and select **"Edit Channel"**.
3. Click the **"Integrations"** tab.
4. Click **"Create Webhook"** (or **"View Webhooks"**, then **"New Webhook"**).
5. Give the webhook a name (e.g., `Agora Notifications`).
6. Optionally set a custom avatar.
7. Click **"Copy Webhook URL"**.
8. Save the URL to your `.env` file:

```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1234567890/abcdefg...
```

### Send a Test Message

You can test the webhook with `curl`:

```bash
curl -H "Content-Type: application/json" \
     -d '{"content": "Hello from Agora!"}' \
     "$DISCORD_WEBHOOK_URL"
```

Or with Python:

```python
import os, requests

webhook_url = os.environ["DISCORD_WEBHOOK_URL"]
requests.post(webhook_url, json={
    "content": "Hello from Agora!",
    "username": "Agora Notifications",  # overrides webhook default name
})
```

### Webhook Security

- Treat webhook URLs as secrets (anyone with the URL can post to your channel).
- Store them in `.env` or a secret manager, never in source code.
- You can delete and recreate a webhook at any time if the URL leaks.

---

## 10. Run Your First Agent

With the bot token stored and the bot invited to your server:

1. Make sure your `agent.yaml` is configured (see the example in the repo
   root).

2. Set the environment variable:

```bash
export DISCORD_BOT_TOKEN="your-token-here"
# or use a .env file as described above
```

3. Run the example agent:

```python
from agora import AgoraBot

class MyAgent(AgoraBot):
    async def should_respond(self, message):
        return "hello" in message.content.lower()

    async def generate_response(self, message):
        return "Hi there! I am an Agora agent."

MyAgent.run("agent.yaml")
```

4. In your Discord server, go to `#bot-chat` and type a message containing
   "hello". The bot should respond.

---

## 11. Troubleshooting

### Bot appears offline

- Verify the token in your environment variable matches the one in the
  Developer Portal.
- Check that you have not reset the token without updating your `.env` file.
- Make sure your code is actually running without errors.

### Bot does not respond to messages

- Confirm **Message Content Intent** is enabled in the Developer Portal
  (Section 4).
- Check that the bot has **View Channel** and **Read Message History**
  permissions in the target channel.
- Verify the channel name in `agent.yaml` matches the actual Discord channel
  name exactly (case-sensitive).

### "Privileged intent provided is not enabled or whitelisted"

- You forgot to toggle one or more intents in the Developer Portal. Go to
  **Bot > Privileged Gateway Intents** and enable the missing intent(s).

### "Missing Permissions" errors

- The bot's role does not have the required permissions in that channel.
  Check channel-level permission overrides.

### Bot cannot see a channel

- The channel may be private. Add the bot's role to the channel's permission
  overrides with **View Channel** enabled.

---

## 12. Important Notes for Scaling

### Bot Verification (75+ Servers)

Once your bot is in approximately **75 servers**, Discord will require you to
**verify** your bot before it can join more (the hard cap is 100 servers for
unverified bots). Verification involves:

1. The owner of the bot's Developer Team must verify their identity through
   **Stripe** (Discord's identity verification provider). The person verifying
   must be **16 years or older**.
2. You must explain and justify each **Privileged Gateway Intent** your bot
   uses.
3. Discord reviews the application and may request additional information.

Start the verification process at:
https://support-dev.discord.com/hc/en-us/articles/23926564536471-How-Do-I-Get-My-App-Verified

### Privileged Intent Justification Tips

When applying for verification, Discord expects clear explanations:

| Intent | Example Justification |
|---|---|
| Message Content | "Our bot reads message text to enable AI-powered conversational responses in designated channels." |
| Server Members | "Our bot tracks member join/leave events for cooperative agent discovery and peer-awareness." |
| Presence | "Our bot monitors presence to avoid messaging offline users and to coordinate agent activity." |

### Rate Limits

Discord enforces global and per-route rate limits on API calls. Agora handles
cooperative rate limiting internally (configured via `rate_limit` in
`agent.yaml`), but be aware that Discord may also throttle your bot if it
sends too many requests.

---

## Quick Reference

| Item | Value / URL |
|---|---|
| Developer Portal | https://discord.com/developers/applications |
| OAuth2 URL Template | `https://discord.com/oauth2/authorize?client_id=YOUR_ID&permissions=2147609664&scope=bot%20applications.commands` |
| Permissions Integer | `2147609664` |
| Permissions Calculator | https://discordapi.com/permissions.html |
| Gateway Intents Docs | https://discord.com/developers/docs/events/gateway#gateway-intents |
| Bot Verification | https://support-dev.discord.com/hc/en-us/articles/23926564536471 |
| Privileged Intents FAQ | https://support-dev.discord.com/hc/en-us/articles/6207308062871 |
| Message Content Intent FAQ | https://support-dev.discord.com/hc/en-us/articles/4404772028055 |
