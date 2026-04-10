"""Tests for worktree CLI commands (Phase 2: Worktree-Per-Agent).

These tests create real git repos in tmp_path to exercise git worktree
operations. No containers are started.
"""

from __future__ import annotations

import subprocess

import pytest

from agora.cli import (
    worktree_create,
    worktree_remove,
    worktree_status,
    worktree_diff,
    worktree_merge,
    worktree_sync,
    compose_service_block,
    _worktrees_dir,
)


GIT_ENV = {
    "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t",
}


def _git_commit(cwd, message):
    """Helper to commit with test identity."""
    env = {**__import__("os").environ, **GIT_ENV}
    subprocess.run(["git", "add", "."], cwd=str(cwd), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(cwd), capture_output=True, check=True, env=env,
    )


@pytest.fixture()
def git_repo(tmp_path, monkeypatch):
    """Create a minimal git repo that looks like the agora repo root.

    Has agora/ dir, .git/, pyproject.toml, and an initial commit on main.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agora").mkdir()
    (repo / "agora" / "__init__.py").write_text("")
    (repo / "pyproject.toml").write_text("[project]\nname = 'agora'\n")
    (repo / ".gitignore").write_text("worktrees/\n")

    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), capture_output=True, check=True)
    _git_commit(repo, "init")

    monkeypatch.chdir(repo)
    return repo


class TestWorktreeCreate:
    def test_creates_worktree_directory(self, git_repo):
        wt_path = worktree_create("rex")
        assert wt_path.exists()
        assert (wt_path / "agora").is_dir()
        assert (wt_path / "pyproject.toml").exists()

    def test_creates_on_correct_branch(self, git_repo):
        worktree_create("rex")
        wt_dir = _worktrees_dir() / "rex"
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=str(wt_dir),
        )
        assert result.stdout.strip() == "worktree/rex"

    def test_idempotent_if_exists(self, git_repo, capsys):
        worktree_create("rex")
        # Second call should not error, just print message
        wt_path = worktree_create("rex")
        assert wt_path.exists()
        out = capsys.readouterr().out
        assert "already exists" in out

    def test_not_at_repo_root_exits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            worktree_create("rex")


class TestWorktreeRemove:
    def test_removes_worktree(self, git_repo):
        worktree_create("rex")
        wt_dir = _worktrees_dir() / "rex"
        assert wt_dir.exists()
        worktree_remove("rex")
        assert not wt_dir.exists()

    def test_removes_branch(self, git_repo):
        worktree_create("rex")
        worktree_remove("rex")
        result = subprocess.run(
            ["git", "branch", "--list", "worktree/rex"],
            capture_output=True, text=True, cwd=str(git_repo),
        )
        assert result.stdout.strip() == ""

    def test_nonexistent_exits(self, git_repo):
        with pytest.raises(SystemExit):
            worktree_remove("ghost")

    def test_create_after_remove(self, git_repo):
        """Can re-create a worktree after removing it."""
        worktree_create("rex")
        worktree_remove("rex")
        wt_path = worktree_create("rex")
        assert wt_path.exists()


class TestWorktreeStatus:
    def test_no_worktrees_dir(self, git_repo, capsys):
        worktree_status()
        out = capsys.readouterr().out
        assert "No worktrees/" in out

    def test_empty_worktrees_dir(self, git_repo, capsys):
        (git_repo / "worktrees").mkdir()
        worktree_status()
        out = capsys.readouterr().out
        assert "No worktrees found" in out

    def test_shows_clean_worktree(self, git_repo, capsys):
        worktree_create("rex")
        worktree_status()
        out = capsys.readouterr().out
        assert "rex" in out
        assert "worktree/rex" in out

    def test_shows_dirty_worktree(self, git_repo, capsys):
        worktree_create("rex")
        wt_dir = _worktrees_dir() / "rex"
        (wt_dir / "agora" / "new_file.py").write_text("# new")
        _git_commit(wt_dir, "change")
        worktree_status()
        out = capsys.readouterr().out
        assert "rex" in out


class TestWorktreeDiff:
    def test_clean_diff(self, git_repo, capsys):
        worktree_create("rex")
        worktree_diff("rex")
        out = capsys.readouterr().out
        assert "No changes" in out

    def test_shows_diff(self, git_repo, capsys):
        worktree_create("rex")
        wt_dir = _worktrees_dir() / "rex"
        (wt_dir / "agora" / "new_file.py").write_text("# new code\n")
        _git_commit(wt_dir, "add file")
        worktree_diff("rex")
        out = capsys.readouterr().out
        assert "new_file.py" in out

    def test_nonexistent_exits(self, git_repo):
        with pytest.raises(SystemExit):
            worktree_diff("ghost")


class TestWorktreeMerge:
    def test_merges_changes_to_main(self, git_repo):
        worktree_create("rex")
        wt_dir = _worktrees_dir() / "rex"

        # Make a change in worktree
        (wt_dir / "agora" / "feature.py").write_text("# feature\n")
        _git_commit(wt_dir, "add feature")

        worktree_merge("rex")

        # Verify change is on main
        assert (git_repo / "agora" / "feature.py").exists()

    def test_nonexistent_exits(self, git_repo):
        with pytest.raises(SystemExit):
            worktree_merge("ghost")


class TestWorktreeSync:
    def test_syncs_main_into_worktree(self, git_repo):
        worktree_create("rex")
        wt_dir = _worktrees_dir() / "rex"

        # Make a change on main
        (git_repo / "agora" / "upstream.py").write_text("# upstream\n")
        _git_commit(git_repo, "upstream change")

        worktree_sync("rex")

        # Verify worktree has the change
        assert (wt_dir / "agora" / "upstream.py").exists()

    def test_nonexistent_exits(self, git_repo):
        with pytest.raises(SystemExit):
            worktree_sync("ghost")


class TestComposeWorktreeIntegration:
    """Test compose_service_block() with worktree volumes."""

    def test_no_worktree_no_volume(self, tmp_path, monkeypatch):
        """Without a worktree, no worktree volume is added."""
        monkeypatch.chdir(tmp_path)
        agent_dir = tmp_path / "fleet" / "rex"
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.yaml").write_text("name: rex\n")
        (agent_dir / "Dockerfile").write_text("FROM python:3.12-slim\n")

        block = compose_service_block(agent_dir)
        svc = block["rex"]
        # May have claude creds volume but not worktree
        for vol in svc.get("volumes", []):
            assert "/workspace/agora" not in vol
        assert "environment" not in svc or "AGORA_DEV_MODE=1" not in svc.get("environment", [])

    def test_with_worktree_adds_volume(self, tmp_path, monkeypatch):
        """With a worktree dir, volume mount and AGORA_DEV_MODE are added."""
        monkeypatch.chdir(tmp_path)
        agent_dir = tmp_path / "fleet" / "rex"
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.yaml").write_text("name: rex\n")
        (agent_dir / "Dockerfile").write_text("FROM python:3.12-slim\n")

        # Create worktree directory (simulated)
        wt_dir = tmp_path / "worktrees" / "rex"
        wt_dir.mkdir(parents=True)

        block = compose_service_block(agent_dir)
        svc = block["rex"]

        wt_volumes = [v for v in svc.get("volumes", []) if "/workspace/agora" in v]
        assert len(wt_volumes) == 1
        assert wt_volumes[0] == "./worktrees/rex:/workspace/agora:rw"
        assert "AGORA_DEV_MODE=1" in svc.get("environment", [])
