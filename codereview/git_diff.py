"""Git diff collection and parsing.

Supports three review sources: committed changes (`base...HEAD`), staged
changes (`git diff --cached <base>`), and all uncommitted changes
(`git diff <base>`). Kept small and deterministic; no complex ignore engine.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_IGNORE = {
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".git",
    ".idea",
    ".vscode",
}

IGNORE_SUFFIXES = (
    ".lock",
    "-lock.json",
    "-lock.yaml",
    ".pyc",
    ".pyo",
    ".min.js",
    ".min.css",
    ".map",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
)


@dataclass
class FileChange:
    path: str
    status: str  # added, modified, deleted, renamed
    old_path: str | None = None
    added_lines: int = 0
    deleted_lines: int = 0


@dataclass
class DiffResult:
    files: list[FileChange] = field(default_factory=list)
    added_lines: int = 0
    deleted_lines: int = 0
    raw_diff: str = ""

    @property
    def files_changed(self) -> int:
        return len(self.files)

    @property
    def total_changed_lines(self) -> int:
        return self.added_lines + self.deleted_lines


def run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run a git command and return stdout, raising RuntimeError on failure."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def _is_ignored(path: str) -> bool:
    parts = Path(path).parts
    if any(p in DEFAULT_IGNORE for p in parts):
        return True
    lower = path.lower()
    return lower.endswith(IGNORE_SUFFIXES)


def _classify_status(raw: str) -> str:
    # raw is like "M", "A", "D", "R100"
    if raw.startswith("R"):
        return "renamed"
    return {"A": "added", "D": "deleted", "M": "modified"}.get(raw, "modified")


def _diff_range(base: str, mode: str) -> list[str]:
    """Return the git diff range arguments for a review source mode.

    Modes:
      head          -- committed changes: base...HEAD
      staged        -- staged (index) changes: git diff --cached <base>
      working-tree  -- all uncommitted changes (staged + unstaged): git diff <base>
    """
    if mode == "head":
        return [f"{base}...HEAD"]
    if mode == "staged":
        return ["--cached", base]
    if mode == "working-tree":
        return [base]
    raise ValueError(f"unknown diff mode: {mode!r}")


def _parse_name_status(
    diff_range: list[str], cwd: Path | None
) -> dict[str, tuple[str, str | None]]:
    """Return {path: (status, old_path)} for changed files."""
    out = run_git(["diff", "--name-status", *diff_range], cwd)
    result: dict[str, tuple[str, str | None]] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = _classify_status(parts[0])
        if len(parts) == 3:
            old_path, new_path = parts[1], parts[2]
            result[new_path] = (status, old_path)
        else:
            result[parts[1]] = (status, None)
    return result


def _untracked_files(cwd: Path | None) -> list[str]:
    """List untracked, non-gitignored files (working-tree mode only)."""
    out = run_git(["ls-files", "--others", "--exclude-standard"], cwd)
    return [line.strip() for line in out.splitlines() if line.strip()]


def _untracked_added_lines(path: Path) -> int | None:
    """Line count of an untracked file, or None if binary/unreadable."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None  # binary
    return len(data.decode("utf-8", errors="replace").splitlines())


def collect_diff(
    base: str, cwd: Path | None = None, mode: str = "head"
) -> DiffResult:
    """Collect the diff for the requested source mode, ignoring noise files."""
    diff_range = _diff_range(base, mode)
    root = cwd or Path.cwd()
    raw_diff = run_git(["diff", *diff_range], cwd)
    name_status = _parse_name_status(diff_range, cwd)

    numstat = run_git(
        ["diff", "--numstat", *diff_range], cwd
    )
    stat: dict[str, tuple[int, int]] = {}
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_raw, deleted_raw, path = parts[0], parts[1], parts[2]
        if added_raw == "-":
            continue  # binary
        stat[path] = (int(added_raw), int(deleted_raw))

    # `git diff <base>` cannot see untracked files; append them as additions
    # so that brand-new AI-generated files are reviewable before commit.
    # raw_diff stays limited to tracked files in this mode.
    if mode == "working-tree":
        for path in _untracked_files(cwd):
            if _is_ignored(path) or path in name_status:
                continue
            lines = _untracked_added_lines(root / path)
            name_status[path] = ("added", None)
            if lines is not None:
                stat[path] = (lines, 0)

    files: list[FileChange] = []
    for path, (status, old_path) in name_status.items():
        if _is_ignored(path) and status == "added":
            continue
        added, deleted = stat.get(path, (0, 0))
        files.append(
            FileChange(
                path=path,
                status=status,
                old_path=old_path,
                added_lines=added,
                deleted_lines=deleted,
            )
        )

    files.sort(key=lambda f: f.path)
    total_added = sum(f.added_lines for f in files if f.status != "deleted")
    total_deleted = sum(f.deleted_lines for f in files if f.status != "added")

    return DiffResult(
        files=files,
        added_lines=total_added,
        deleted_lines=total_deleted,
        raw_diff=raw_diff,
    )


def get_file_content(ref: str, path: str, cwd: Path | None = None) -> str | None:
    """Return file content at a given git ref, or None if it does not exist."""
    try:
        return run_git(["show", f"{ref}:{path}"], cwd)
    except RuntimeError:
        return None


def get_staged_file(path: str, cwd: Path | None = None) -> str | None:
    """Return the staged (index) copy of a file, or None if not staged."""
    try:
        return run_git(["show", f":{path}"], cwd)
    except RuntimeError:
        return None


def get_working_tree_file(path: str, cwd: Path | None = None) -> str | None:
    """Return working-tree copy of a file, or None if missing."""
    p = (cwd or Path.cwd()) / path
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8", errors="replace")