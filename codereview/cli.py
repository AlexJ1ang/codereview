"""Command-line interface for codereview."""
from __future__ import annotations

from pathlib import Path

import typer

from .review import run_review
from .report import render_json, render_text

app = typer.Typer(
    name="codereview",
    help="Review code changes for unnecessary implementation complexity.",
    add_completion=False,
    no_args_is_help=True,
)


@app.callback()
def _callback() -> None:
    """Keep `review` as a proper subcommand (disables single-command promo)."""


@app.command()
def review(
    base: str = typer.Option(..., "--base", help="Base branch, e.g. main"),
    task: str = typer.Option(..., "--task", help="Natural-language description of the task"),
    cwd: Path | None = typer.Option(
        None, "--cwd", help="Repository root (defaults to current directory)"
    ),
    staged: bool = typer.Option(
        False, "--staged", help="Review staged (index) changes instead of committed ones"
    ),
    working_tree: bool = typer.Option(
        False,
        "--working-tree",
        help="Review all uncommitted changes (staged + unstaged)",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of text"),
) -> None:
    """Review code changes against `base` for implementation overhead."""
    if staged and working_tree:
        typer.echo(
            "Error: --staged and --working-tree are mutually exclusive.", err=True
        )
        raise typer.Exit(code=2)
    source = "working-tree" if working_tree else "staged" if staged else "head"
    try:
        report = run_review(base=base, task=task, cwd=cwd, source=source)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if json_out:
        typer.echo(render_json(report))
    else:
        typer.echo(render_text(report))


def main() -> None:
    app()