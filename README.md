# airlock_toy

A weekend-built toy that demonstrates the **agent-airlock** pattern: two
Docker containers per task with a `docker exec` "airlock" between them, plus
a tiny host-side broker daemon for privileged operations (real `git push` with
the host's SSH key). Claude Code lives in the agent container, acts on the
sealed code container via the airlock, and asks the broker to do anything
that needs host credentials.

This is a **toy** — built to validate the airlock concept end-to-end before
committing to a v1 product. It demonstrates the mechanic honestly; it is not
hardened. See "Security note" below.

Strategy and design context: `~/system_designer/designs/2026-04-26/agent-code-sandbox/strategy.md`
and `~/system_designer/designs/2026-04-26/agent-airlock-toy/system-design.md`.

## What it does

Given a git repo and a task description, the toy:

1. Creates a git worktree of the repo at `<repo>/../airlock-<id>/` on a fresh
   `airlock/<id>` branch.
2. Starts a host-side broker daemon listening on `/tmp/airlock-<id>.sock`.
3. Starts a sealed **code container** (`--network none`, `--read-only` root,
   no host secrets) with the worktree bind-mounted at `/workspace`.
4. Starts an **agent container** holding Claude Code, the docker CLI, and a
   tiny `broker_client.sh`. The host's docker socket is mounted in so the
   agent can `docker exec` into the code container — that exec is the airlock.
5. Runs Claude Code inside the agent container with a system prompt teaching
   it to use `docker exec $CODE_CONTAINER bash -c '<cmd>'` for everything,
   and `broker_client.sh git_push <branch>` for pushing.
6. On exit (clean or `Ctrl-C`), stops both containers, kills the broker, and
   asks whether to remove the worktree.

## Prerequisites

- Docker installed and running. On Mac, Docker Desktop or OrbStack-pretending-
  to-be-Docker. On Linux, native Docker.
- `ANTHROPIC_API_KEY` set in your environment or in a `.env` next to `run.sh`.
- An SSH key loaded in `ssh-agent` (`ssh-add ~/.ssh/id_ed25519`) for the
  broker to use when pushing.
- Python 3 on the host (only stdlib used; any 3.10+ works).

## Quick start

```bash
git clone <this repo>
cd airlock_toy
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
./run.sh ./examples/broken_calc "fix the failing test in test_calc.py"
```

On first run, `run.sh` builds the two images (`airlock-code:latest` and
`airlock-agent:latest`). Subsequent runs reuse them.

You'll see:
- Worktree creation log.
- Broker socket bound.
- Both containers starting.
- Claude Code's output as it reads the code, identifies the bug
  (`add(a, b): return a - b`), edits it, runs pytest, and pushes.
- Cleanup prompt at the end.

The example repo `examples/broken_calc/` is its own git repo with no `origin`
remote, so the final `git_push` will fail with a clear error from the broker.
That's expected for the included example; point the toy at a repo with a real
remote to see the broker push.

## Layout

```
airlock_toy/
├── run.sh              # entrypoint; validates prereqs, builds images, calls launcher
├── launcher.py         # creates worktree, starts broker + 2 containers, runs claude
├── broker.py           # host-side daemon — git push/fetch on host with SSH agent
├── broker_client.sh    # 30-line nc client used inside the agent container
├── Dockerfile.code     # python + pytest + tooling. No agent. Network none at runtime.
├── Dockerfile.agent    # node + claude + docker CLI + nc + broker_client.sh
├── examples/
│   └── broken_calc/    # tiny git repo with a deliberately failing pytest
└── .beads/             # task tracking for this toy's own implementation
```

## Manual testing

Bring the containers up without invoking Claude (handy for poking around):

```bash
ANTHROPIC_API_KEY=stub python3 launcher.py --no-claude ./examples/broken_calc "smoke"
```

Then in another terminal:

```bash
docker ps                                              # see both containers
docker exec -it airlock-code-<id> bash                 # inside the sealed sandbox
docker exec -it airlock-agent-<id> bash                # where Claude would run
```

Inside the agent container you can `docker exec $CODE_CONTAINER bash -c '...'`
to feel out the airlock yourself, or pipe a JSON line to `nc -U /broker.sock`
to talk to the broker manually.

`Ctrl-C` the launcher to clean everything up.

## Security note (read this)

The toy mounts `/var/run/docker.sock` from the host into the agent container.
This is what gives the agent the ability to `docker exec` into the code
container — i.e., the airlock works because of this mount. **It is also a
known security trade-off:** any process inside the agent container with
access to the docker socket can run arbitrary `docker run` commands on the
host (including `docker run -v /:/host` to mount the entire host filesystem).

In the toy this is acceptable because:

- The agent inside is Claude Code — semi-trusted, not adversarial.
- The toy is a development artifact, not a production substrate.
- The whole point of building it is to *see the airlock work* end-to-end so
  v1 can replace the docker-socket mount with a narrower mechanism.

For v1, the docker-socket mount is replaced with a narrow `code_exec` op on
the host broker — same shape as the existing `git_push` op. The agent emits
`{"op": "code_exec", "container": "airlock-code-<id>", "cmd": "..."}` and the
broker validates the container belongs to the current task before executing.
That keeps the airlock concept while removing the docker-host-equivalence.

What the toy *does* protect against, today:

- The agent container has no host SSH keys, no AWS creds, no host home dir.
- The code container has no internet (`--network none`), no host filesystem
  beyond the worktree, no secrets at all.
- Pushes can only target branches matching `^airlock/[a-z0-9-]+$` and only
  to `origin`. The broker rejects everything else.
- All file edits made via the airlock land in the worktree, on the `airlock/`
  branch — never on `main`.

## What's next (toy → v1)

The strategy run that produced this toy
(`~/system_designer/designs/2026-04-26/agent-code-sandbox/strategy.md`)
calls out the obvious v1 directions:

- Replace the docker-socket mount with a narrow `code_exec` broker op.
- Egress allowlist for the code container (today: `--network none`).
- Profile auto-detection (today: hand-write a Dockerfile.code per stack).
- Multi-task fleet: many `{agent, code}` *pairs* in parallel, one shared
  broker. The current toy is single-task.
- Cost ledger so you can see the per-task token spend.
- Per-effect ephemerality (snapshot/restore the code container per tool call)
  if the response from the toy makes it worth doing.

Open work for the toy itself is tracked in beads:

```bash
bd list --status=open    # what's left
bd ready                 # what's unblocked
```

## License

Whatever the user picks. (Toy.)
