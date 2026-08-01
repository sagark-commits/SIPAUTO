"""Minimal console helpers (stdlib). No rich/typer required."""

from __future__ import annotations

import getpass
import sys
from typing import Any, Iterable, Optional, Sequence


def _strip_markup(text: str) -> str:
    out = text
    for tag in (
        "[green]",
        "[/green]",
        "[red]",
        "[/red]",
        "[yellow]",
        "[/yellow]",
        "[cyan]",
        "[/cyan]",
        "[dim]",
        "[/dim]",
        "[bold]",
        "[/bold]",
    ):
        out = out.replace(tag, "")
    return out


class Console:
    def print(self, *args: Any, **kwargs: Any) -> None:
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        text = sep.join(str(a) for a in args)
        sys.stdout.write(_strip_markup(text) + end)
        sys.stdout.flush()

    def input(self, prompt: str = "") -> str:
        return input(_strip_markup(prompt))

    def rule(self, title: str = "") -> None:
        line = "-" * 60
        if title:
            console.print(f"\n{line}\n  {title}\n{line}")
        else:
            console.print(line)

    @property
    def is_terminal(self) -> bool:
        return sys.stdin.isatty() and sys.stdout.isatty()


console = Console()


class Panel:
    """Compat shim: Panel(body, title=..., style=...) printable via console.print."""

    def __init__(self, body: str = "", title: str = "", style: str = ""):
        self.body = body
        self.title = title
        self.style = style

    def __str__(self) -> str:
        title = self.title or "SIPAUTO"
        line = "=" * min(72, max(20, len(title) + 8))
        parts = [line, f"  {title}"]
        if self.body:
            parts.append(str(self.body))
        parts.append(line)
        return "\n".join(parts)


def panel(title: str, body: str = "") -> None:
    console.print(Panel(body, title=title))


def ask(prompt: str, default: Optional[str] = None, password: bool = False) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        if password:
            raw = getpass.getpass(f"{prompt}{suffix}: ")
        else:
            raw = input(f"{prompt}{suffix}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        console.print("Value required.")


def ask_text(prompt: str, default: str = "") -> str:
    return ask(prompt, default=default)


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    return confirm(prompt, default=default)


def ask_choice(prompt: str, choices: Sequence[str], default: str = "") -> str:
    allowed = {c.lower(): c for c in choices}
    while True:
        raw = ask(prompt, default=default).strip()
        if raw.lower() in allowed:
            return allowed[raw.lower()]
        console.print(f"Pick one of: {', '.join(choices)}")


def confirm(prompt: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        console.print("Please enter y or n")


def print_table(title: str, headers: list[str], rows: Iterable[list[str]]) -> None:
    row_list = [list(map(str, r)) for r in rows]
    cols = list(headers)
    widths = [len(h) for h in cols]
    for row in row_list:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))
    console.print(f"\n{title}")
    hdr = " | ".join(h.ljust(widths[i]) for i, h in enumerate(cols))
    console.print(hdr)
    console.print("-+-".join("-" * w for w in widths))
    for row in row_list:
        console.print(
            " | ".join(
                row[i].ljust(widths[i]) if i < len(row) else "".ljust(widths[i])
                for i in range(len(cols))
            )
        )
    console.print("")
