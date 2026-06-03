"""Small terminal rendering helpers for the demo CLI."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .skill import SkillState


def render_skill_state_bar(mastery: float, *, width: int = 20) -> str:
    """Render a stable ASCII bar for a Skill mastery estimate."""
    if width < 1:
        raise ValueError("width must be >= 1")
    bounded = max(0.0, min(1.0, mastery))
    filled = round(bounded * width)
    return f"[{'#' * filled}{'-' * (width - filled)}]"


def render_skill_state_rows(session_state: Mapping[str, Any], *, width: int = 20) -> list[str]:
    """Render sorted final/live Skill states from a Session state mapping."""
    rows: list[str] = []
    metadata = session_state.get("skill_metadata", {})
    for skill, raw in sorted(session_state.get("skill_states", {}).items()):
        state = SkillState(skill=str(raw["skill"]), alpha=float(raw["alpha"]), beta=float(raw["beta"]))
        criticality = metadata.get(skill, {}).get("role_criticality", "unknown")
        rows.append(
            f"{skill:<18} {render_skill_state_bar(state.mastery, width=width)} "
            f"mastery={state.mastery:>5.0%} confidence={state.confidence:>5.0%} "
            f"criticality={criticality}"
        )
    return rows
