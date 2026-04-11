---
name: engineer
description: End-to-end engineering pipeline — concept through trade study, blueprint, build, and PR. Always on a feature branch, always ends with a pull request.
argument-hint: "<idea or problem description>"
triggers:
  - engineer
  - engineer this
  - full pipeline
  - end to end
  - concept to build
  - take this all the way
  - the whole thing
  - soup to nuts
  - from scratch
  - make it real
  - figure it out and build it
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Agent
  - WebFetch
  - WebSearch
---

# Engineer

Run the full engineering pipeline: **Concept → Trade Study → Blueprint → Build → PR**.

Takes a raw idea and delivers a pull request with working code. Every run happens on a fresh feature branch. The PR is created regardless of outcome — if the build fails or is incomplete, the PR title is prefixed with `[FAIL]` so the operator knows not to merge.

## Input

A description of the idea, problem, or feature to engineer. Can be a sentence, a paragraph, or a rambling voice note. The skill extracts the core intent.

## Process

### Phase 0: Setup

1. **Derive a slug** from the idea (lowercase, hyphenated, 2-4 words). This is used for the branch name and bead titles.

2. **Create a feature branch** from main:
   ```bash
   git checkout main && git pull --ff-only 2>/dev/null; git checkout -b feature/<slug>
   ```

3. **Set a status variable** to track pipeline outcome:
   - `PIPELINE_STATUS=pass` (will flip to `fail` if any phase fails critically)

### Phase 1: Concept

Capture the idea as a single bead. Follow the concept skill's process:

1. Optionally explore 1-3 relevant files to ground the idea.
2. Create ONE bead:
   ```bash
   bd create --title="<concise title>" \
     --description="<what and why>" \
     --type=feature \
     --labels=concept \
     --design="<3-10 sentence design sketch>"
   ```
3. Save the bead ID as `CONCEPT_ID`.

**Report to user**: Brief summary of the concept captured.

### Phase 2: Trade Study

Explore 3 implementation variants. Follow the trade study skill's process:

1. **Ground the concept** — read 1-5 relevant files in the codebase. This is mandatory.
2. **Convert the concept to a trade study epic**:
   ```bash
   bd update $CONCEPT_ID --type=feature --labels=trade-study
   bd update $CONCEPT_ID --design="<trade-space dimensions and evaluation criteria>"
   ```
3. **Create 3 variant child beads** (each a genuinely different approach):
   ```bash
   bd create --title="Variant: <approach name>" \
     --type=task \
     --parent=$CONCEPT_ID \
     --labels=trade-study-variant \
     --design="<approach, how it works, trade-offs, effort, what it enables, what it limits>"
   ```
4. **Pick a winner.** Unlike standalone trade study (which doesn't pick), engineer mode MUST select the best variant for the project. Justify briefly.
5. Save the winning variant ID as `WINNER_ID`.

**Report to user**: The 3 variants (2-3 lines each) and which was selected and why.

### Phase 3: Blueprint

Promote the winning variant to an actionable plan. Follow the blueprint skill's process:

1. **Convert to blueprint**:
   ```bash
   bd update $WINNER_ID --type=epic --labels=blueprint
   bd update $WINNER_ID --design="<implementation plan: approach, file changes, acceptance criteria>"
   bd update $WINNER_ID --metadata '{"target_repo": "<repo>"}'
   ```
2. **Create 2-6 child tasks** under the blueprint epic:
   ```bash
   bd create --title="<task>" --type=task --priority=2 --parent=$WINNER_ID \
     --description="<what to do, which files, expected outcome>"
   ```
3. **Wire dependencies**:
   ```bash
   bd dep add <downstream> <upstream>
   ```

**Report to user**: Task list with dependency order.

### Phase 4: Build

Execute the blueprint. Follow the build skill's process:

1. **Load the blueprint**: `bd show $WINNER_ID` and review child tasks.
2. **Task loop** (dependency order):
   - Claim: `bd update <task-id> --status=in_progress`
   - Implement the change
   - Verify (run tests if applicable)
   - Commit: `git commit -m "<type>(<scope>): <description> (<task-id>)"`
   - Close: `bd close <task-id> --reason="<what was done>"`
3. **If a task fails**: 
   - Add a note to the bead describing what went wrong.
   - Set `PIPELINE_STATUS=fail`.
   - Continue to the next task if possible, or stop if blocked.
4. **After all tasks**: Run full verification (tests, lint if available).
5. **Close the epic** (if all tasks succeeded):
   ```bash
   bd close $WINNER_ID --reason="All tasks completed"
   ```

### Phase 5: Pull Request

Create a PR **regardless of outcome**. This is non-negotiable.

1. **Determine PR title**:
   - If `PIPELINE_STATUS=pass`: `<concise description of what was built>`
   - If `PIPELINE_STATUS=fail`: `[FAIL] <concise description of what was attempted>`

2. **Build PR body** summarizing all phases:
   ```bash
   gh pr create --title "<title>" --body "$(cat <<'EOF'
   ## Summary
   <1-3 bullets: what this PR does>

   ## Pipeline
   - **Concept**: <bead ID> — <one-line summary>
   - **Trade Study**: <3 variants considered, winner chosen>
   - **Blueprint**: <N tasks planned>
   - **Build**: <N/M tasks completed>

   ## Status
   <PASS: ready for review / FAIL: description of what broke and where>

   ## Test plan
   - [ ] <verification steps>

   Generated with `/engineer` pipeline
   EOF
   )"
   ```

3. **Push and create**:
   ```bash
   git push -u origin feature/<slug>
   gh pr create ...
   ```

4. **Report the PR URL** to the user.

## Rules

- **Always branch.** Never engineer on main/master.
- **Always PR.** Even if the build fails at task 1, push what you have and open the PR with `[FAIL]`.
- **Pick a winner.** Unlike standalone `/trade-study`, this skill must choose and commit to a variant.
- **One commit per task.** Don't batch commits.
- **Don't get stuck.** If a task is blocked, mark it failed, note why, and move on. The PR will reflect the incomplete state.
- **No markdown planning files.** Everything lives in beads.
- **Stay on the feature branch.** Don't switch branches mid-pipeline.
- **Close beads as you go.** Don't leave beads in_progress when you're done with them.
- **Report after each phase.** The user should see concept → variants → blueprint → build progress, not just a final dump.
