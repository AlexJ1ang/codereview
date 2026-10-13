"""End-to-end tests for the three review source modes.

Each test builds a tiny git repository in tmp_path and runs the full
review pipeline without LLM configuration (deterministic detectors only).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codereview.cli import app
from codereview.review import run_review

OVERENGINEERED = '''\
class ResultProcessor:
    """Single-method, stateless class created for one call site."""

    def process(self, value):
        return value
'''


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "tester")
    (tmp_path / "helper.py").write_text(
        "def existing_helper():\n    return 1\n", encoding="utf-8"
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    return tmp_path


def _write_overengineered(repo: Path) -> None:
    (repo / "new_module.py").write_text(OVERENGINEERED, encoding="utf-8")


def _has_one_use_class(report: dict) -> bool:
    return any(
        a["kind"] == "one-use-class" and a["name"] == "ResultProcessor"
        for a in report["abstractions"]
    )


def test_head_mode_only_sees_committed_changes(repo: Path) -> None:
    _write_overengineered(repo)
    report = run_review(base="main", task="add result processing", cwd=repo)
    assert report["source"] == "head"
    assert report["change_summary"]["files_changed"] == 0
    assert not _has_one_use_class(report)


def test_working_tree_mode_reviews_uncommitted(repo: Path) -> None:
    _write_overengineered(repo)
    report = run_review(
        base="main", task="add result processing", cwd=repo, source="working-tree"
    )
    assert report["source"] == "working-tree"
    assert report["change_summary"]["files_changed"] == 1
    assert report["change_summary"]["new_classes"] == 1
    assert _has_one_use_class(report)


def test_staged_mode_reads_index_not_working_tree(repo: Path) -> None:
    _write_overengineered(repo)
    _git(repo, "add", "new_module.py")
    # Dirty the working tree afterwards; the staged report must not change.
    (repo / "new_module.py").write_text("value = 1\n", encoding="utf-8")
    report = run_review(base="main", task="t", cwd=repo, source="staged")
    assert report["source"] == "staged"
    assert report["change_summary"]["files_changed"] == 1
    assert _has_one_use_class(report)


def test_head_mode_reads_committed_not_working_tree(repo: Path) -> None:
    _git(repo, "checkout", "-b", "feature")
    _write_overengineered(repo)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add module")
    # Dirty the working tree afterwards; the head report must not change.
    (repo / "new_module.py").write_text("value = 1\n", encoding="utf-8")
    report = run_review(base="main", task="t", cwd=repo, source="head")
    assert report["change_summary"]["files_changed"] == 1
    assert _has_one_use_class(report)


def test_deleted_file_counts_toward_complexity_delta(repo: Path) -> None:
    (repo / "gone.py").write_text(
        "def a():\n    if x:\n        return 1\n    return 2\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add gone")
    (repo / "gone.py").unlink()
    report = run_review(base="main", task="remove module", cwd=repo, source="working-tree")
    assert report["change_summary"]["files_changed"] == 1
    assert report["complexity"]["delta"] < 0


def test_syntactically_invalid_file_does_not_crash(repo: Path) -> None:
    (repo / "broken.py").write_text("def oops(:\n    pass\n", encoding="utf-8")
    report = run_review(base="main", task="t", cwd=repo, source="working-tree")
    assert report["change_summary"]["files_changed"] == 1
    assert report["change_summary"]["new_functions"] == 0
    assert report["change_summary"]["lines_added"] == 2


def test_cli_rejects_staged_with_working_tree(repo: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "review", "--base", "main", "--task", "t",
            "--staged", "--working-tree", "--cwd", str(repo),
        ],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_unknown_source_raises(repo: Path) -> None:
    with pytest.raises(ValueError, match="unknown source"):
        run_review(base="main", task="t", cwd=repo, source="nope")
