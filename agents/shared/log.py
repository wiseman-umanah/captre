"""
shared/log.py — Rich terminal logger for the agent world.

Produces a coloured, timestamped stream of agent activity.
Each agent has a fixed colour so you can visually track actors
as they interleave in the terminal.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Literal

from rich.console import Console
from rich.text import Text

# One global console, thread-safe
_console = Console()
_lock = threading.Lock()

# Colour palette — one per agent name
_PALETTE: dict[str, str] = {
    "BANK":       "bold yellow",
    "RESEARCHER": "bold cyan",
    "CODER":      "bold green",
    "AUDITOR":    "bold magenta",
    "CRITIC":     "bold red",
}
_DEFAULT_COLOUR = "bold white"

# Action-level icon + colour
_ACTION_STYLE: dict[str, tuple[str, str]] = {
    "ATTEST":   ("📝", "green"),
    "REVOKE":   ("🗑 ", "red"),
    "VERIFY":   ("🔍", "cyan"),
    "FUND":     ("💰", "yellow"),
    "INFO":     ("ℹ️ ", "white"),
    "ERROR":    ("❌", "bold red"),
    "SUCCESS":  ("✅", "bold green"),
    "WAIT":     ("⏳", "dim white"),
}


def log(
    agent: str,
    action: Literal["ATTEST", "REVOKE", "VERIFY", "FUND", "INFO", "ERROR", "SUCCESS", "WAIT"],
    message: str,
    detail: str | None = None,
) -> None:
    """
    Emit a single log line to the terminal.

    Parameters
    ----------
    agent : str
        Agent name (e.g. "RESEARCHER"). Used for colouring.
    action : str
        High-level action category driving the icon and action colour.
    message : str
        Human-readable description of what just happened.
    detail : str or None
        Optional short detail appended in dim grey (e.g. attestation_id, hash).
    """
    now = datetime.now(tz=UTC).strftime("%H:%M:%S")
    icon, action_colour = _ACTION_STYLE.get(action, ("•", "white"))
    agent_colour = _PALETTE.get(agent.upper(), _DEFAULT_COLOUR)

    line = Text()
    line.append(f"[{now}] ", style="dim white")
    line.append(f"{agent:<12}", style=agent_colour)
    line.append(f"  {icon} ", style=action_colour)
    line.append(f"{message}", style="white")
    if detail:
        line.append(f"  {detail}", style="dim white")

    with _lock:
        _console.print(line)


def banner(title: str) -> None:
    """
    Print a full-width section banner.

    Parameters
    ----------
    title : str
        Text to display inside the banner.
    """
    with _lock:
        _console.rule(f"[bold white]{title}[/bold white]", style="dim white")
