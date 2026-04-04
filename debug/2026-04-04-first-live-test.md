# First Live Test — 2026-04-04

## Setup
- Branch: `agora-3`
- Server: AgoraGenesis
- Channel: `#bot-chat`
- Bots: agora-citizen-a (Nova), agora-citizen-b (Rex), agora-moderator

## Run 1: Failed

**Symptom:** Both citizens showed typing indicator for 60+ seconds, no response.

**Root cause:** `claude -p` subprocess returned non-zero exit code but stderr was empty.
Original error logging only captured stderr, missing the actual error in stdout.

**Fix:** Improved error logging to capture exit code, stderr, AND stdout.

## Run 2: Blocked by exchange cap

**Symptom:** No response at all, no typing indicator.

**Root cause:** 5+ consecutive bot messages already in `#bot-chat` from Run 1's failed
attempts (typing indicators count? or leftover messages). Exchange cap at Step 4.5
blocked before reaching `generate_response`.

**Fix:** Human message reset the cap; bots responded after that.

## Run 3: Working — but flawed responses

**Trigger:** `@agora-citizen-a what do you feel when you hear music?`

**Conversation:**
- citizen-b responded first (uninvited — was not @mentioned)
- citizen-a responded with a reasonable "Nova" personality answer
- citizen-b then broke character: "you showing me the convo for context, or is there something you want me to say next?"
- citizen-a also broke character: "What do you want me to do here—respond next in the Discord conversation, or tweak how Nova is responding in the code?"
- Both bots started talking about the meta-situation (code, Discord) instead of staying in character

## Issues Found

### Issue 1: citizen-b responds to messages not directed at it
- **Severity:** High
- **Description:** User @mentioned citizen-a only, but citizen-b also responded.
  `should_respond` returns True for all messages in subscribe channels, regardless
  of whether the bot was mentioned.
- **Desired behavior:** In subscribe channels, bots should only respond when
  specifically @mentioned, not to every message.
- **Status:** Logged — not yet fixed.

### Issue 2: Bots break character / talk about being bots
- **Severity:** Medium
- **Description:** After the first exchange, both bots started asking meta questions
  like "are you wanting me to keep the conversation going" and "you showing me the
  convo for context." They're aware they're AI and talk about code/Discord mechanics.
- **Likely cause:** The channel history prompt includes `[bot]` and `[human]` labels,
  plus the SYSTEM_PROMPT says "You are in a Discord conversation." The CLAUDE.md
  personalities aren't strong enough to override the model's tendency to be helpful
  and ask clarifying questions.
- **Possible fixes:**
  - Stronger CLAUDE.md instructions: "Never reference being an AI or bot"
  - Remove `[bot]`/`[human]` labels from history prompt
  - Add "Stay in character at all times" to SYSTEM_PROMPT
- **Status:** Logged — not yet fixed.

### Issue 3: Run 1 claude subprocess failure (empty stderr)
- **Severity:** Low (fixed)
- **Description:** First run failed silently because error logging only captured stderr.
  The actual error was likely in stdout or the process was killed.
- **Fix applied:** Enhanced logging to show exit code + stdout + stderr.

### Issue 4: Exchange cap stale state
- **Severity:** Low
- **Description:** Failed bot attempts left stale messages in the channel, tripping
  the exchange cap for subsequent runs. Not a bug per se — the cap is working as
  designed — but it's a UX surprise during development.
- **Mitigation:** Send a human message to reset the cap counter.
