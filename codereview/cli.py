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
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of text"),
) -> None:
    """Review the current branch against `base` for implementation overhead."""
    try:
        report = run_review(base=base, task=task, cwd=cwd)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if json_out:
        typer.echo(render_json(report))
    else:
        typer.echo(render_text(report))


def main() -> None:
    app()