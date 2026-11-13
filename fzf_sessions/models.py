"""Models for fzf-sessions."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Session:
    tool: str
    id: str
    title: str
    cwd: str
    updated: float
    transcript: str = ""
    branch: str = ""
    herdr_locations: list[dict[str, str]] = field(default_factory=list)
    herdr_checked: bool = False


@dataclass
class Usage:
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    context_tokens: int | None = None
    context_limit: int | None = None
    recorded_at: str = ""
