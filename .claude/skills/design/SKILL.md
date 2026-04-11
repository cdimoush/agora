---
name: design
description: Run a reviewed design session — draft from existing notes/context, pressure-test through multi-agent review rounds, produce a final design document
argument-hint: <slug> "<description>" [--rounds N] [--reviewers N] [--inputs file1 file2 ...]
triggers:
  - design session
  - design document
  - write a design
  - full design
  - design review
  - reviewed design
---

# /design skill

You are running a **reviewed design session**. You will gather existing context, draft a design, run it through multiple rounds of independent reviewer agents, incorporate feedback, and produce a final document. No web research unless explicitly requested — the inputs are the research.

**Input**: `$ARGUMENTS`
- First word: **slug** (e.g., `phase2-api`)
- Quoted string or remaining words: **description**
- `--rounds N`: review rounds (default 2)
- `--reviewers N`: reviewers per round (default 3)
- `--inputs file1 file2 ...`: specific files to use as input context

Parse these from `$ARGUMENTS`. If empty or missing a description, ask the user.

**Date**: Use today's date from system context, format `YYYY-MM-DD`.

**Working directory**: All output goes to `designs/<date>/<slug>/` within the workspace.

---

## Phase 1: Gather & Draft

### Step 1: Setup

1. Parse `SLUG`, `DESC`, `ROUNDS`, `REVIEWERS`, and `INPUTS` from arguments.
2. Run the scaffold script to pre-create all beads:
   ```bash
   scripts/scaffold-design.sh "$SLUG" "$DESC" --rounds $ROUNDS --reviewers $REVIEWERS
   ```
   Capture the output — it contains bead IDs in KEY=VALUE format.
3. Create the output directory:
   ```bash
   mkdir -p "designs/$TODAY/$SLUG"
   ```

### Step 2: Gather input materials

Read all available context. Sources, in priority order:

1. **Explicit inputs** — files passed via `--inputs`. Read all of them.
2. **Today's notes** — `notes/$TODAY/*.md` (always check, these are conversation artifacts).
3. **Related beads** — `bd search "<slug or keywords>"` for prior concepts, trade studies, or blueprints.
4. **Current Agora source** — read relevant files from the codebase to ground the design. Use Glob and Grep, not exhaustive reads. Focus on the public API surface and any modules the design would touch.

### Step 3: Write the draft

Claim the draft bead (`bd update $DRAFT_ID --claim`).

Write `designs/$TODAY/$SLUG/draft.md`. This is the working document that reviewers will read and that edits will modify in place. Structure:

```markdown
# <Title> — Design Draft

## Context
<What prompted this design. Link to input materials.>

## Problem
<What specific problem does this solve? Who has it? Why now?>

## Proposed Design
<The core of the document. Architecture, components, interfaces, data flow.
Be concrete — name classes, methods, config fields. Reference existing Agora code where relevant.
Use ASCII diagrams or pseudocode where they clarify.>

## Trade-offs
<What alternatives were considered? Why this approach over others?
If a trade study exists, reference it.>

## Scope
<What's in. What's explicitly out. What's deferred.>

## Open Questions
<Things you aren't sure about. Things that need user input.>
```

Also initialize `designs/$TODAY/$SLUG/journal.md`:

```markdown
# <Title> — Design Journal

## Draft — <date>
### Sources used
<List of all input materials read>
### Key decisions in initial draft
<What choices were made and why>
```

Close the draft bead.

---

## Phase 2: Review Cycle

Repeat for each round (1 through ROUNDS):

### Step 1: Fan out to reviewers

Launch all reviewers for this round **in parallel** via the Agent tool. Each reviewer gets a **fresh context window** — no conversation history, no prior feedback. Each gets:

```
You are a design reviewer for the Agora project.

Agora is a Python library that lets anyone add an AI agent to a shared Discord server.
No central orchestrator — Discord is the infrastructure. Each operator installs the library,
configures their bot token and LLM, and connects directly.

## Your Assignment

Review the design document below through the **<lens-name>** lens.

<paste the lens description from the bead>

## The Draft

<paste the full contents of designs/<today>/<slug>/draft.md>

## Instructions

Write your review as structured feedback:

1. **What works well** (1-3 points — be specific, cite sections)
2. **What needs improvement** (1-5 points — each must cite the section it refers to and explain *why* it's a problem, not just *that* it is)
3. **Unanswered questions** the draft should address
4. **Top recommendation** — the single change that would most improve this design

Write your feedback. Be direct, be specific, cite sections. Do not be generically positive.
```

Each reviewer agent writes its feedback. Capture the feedback and write it to the reviewer's bead notes:
```bash
bd update $REVIEWER_ID --notes "<feedback>"
bd close $REVIEWER_ID
```

### Step 2: Synthesize and edit

Claim the edit bead for this round.

Read all reviewer feedback from this round (from bead notes). Then:

1. **Synthesize** — find the themes. Where do reviewers agree? Where do they disagree? Which feedback is actionable vs. subjective?

2. **Edit draft.md** — make concrete changes. Don't just acknowledge feedback — actually modify the document. Use the Edit tool, not full rewrites, so the diff is visible.

3. **Update journal.md** — append:
   ```markdown
   ## Round N Edits — <date>
   ### Reviewer feedback summary
   <Theme 1: what reviewers said, what you changed>
   <Theme 2: ...>
   ### Feedback not incorporated
   <What you chose to skip and why>
   ### Changes made
   <Bullet list of substantive changes to the draft>
   ```

4. Close the edit bead.

---

## Phase 3: Finalize

Claim the finalize bead.

Write `designs/$TODAY/$SLUG/design.md` — the **final document**. This is a clean rewrite of the draft incorporating all review rounds. Don't just copy draft.md — restructure for clarity and completeness:

```markdown
# <Title> — System Design

## Summary
<1-2 paragraphs: what this is, why it matters, what it proposes>

## Problem Statement
<Expanded from draft, refined by review feedback>

## Design

### Overview
<High-level architecture. Block diagram if useful.>

### <Component/Section 1>
<Details — interfaces, behavior, config>

### <Component/Section 2>
<...>

## API Surface
<What operators will actually use. Classes, methods, config fields.
Show a minimal usage example.>

## Migration / Compatibility
<How this relates to what exists today. Breaking changes? Gradual adoption?>

## Trade-offs & Alternatives
<Refined from draft — review feedback often surfaces new trade-offs>

## Risk Register
| Risk | Impact | Mitigation |
|------|--------|------------|
| ...  | ...    | ...        |

## Implementation Roadmap
<Suggested build order. What to build first and why. NOT time estimates.>

## Open Questions
<Anything intentionally deferred to implementation time>

## Appendix
- [Design Journal](journal.md)
- [Draft with review history](draft.md)
```

Update journal.md with final entry:
```markdown
## Final — <date>
### Summary of evolution
<How the design changed from draft through review rounds>
### Confidence level
<How solid is this design? What still feels uncertain?>
```

Close the finalize bead and the parent epic.

Report to the user: brief summary of the design, how many review rounds it went through, key changes that emerged from review, and the file paths.

---

## Rules

- **No code changes.** This skill produces documents, not implementation. That's `/build`.
- **No web research by default.** The inputs are the research. If the user asks for web research, do it, but it's not part of the standard flow.
- **Reviewers are independent.** They don't see each other's feedback within a round. They don't see prior conversation. Fresh eyes every time.
- **Edit, don't rewrite.** Use the Edit tool on draft.md so changes are traceable. Only the final document is a clean write.
- **Everything in beads.** No TodoWrite, no markdown task lists. Beads track all progress.
- **Journal is the audit trail.** Every decision, every piece of feedback incorporated or rejected, goes in the journal.
- **Designs live in the workspace.** Output directory is `designs/<date>/<slug>/`.
