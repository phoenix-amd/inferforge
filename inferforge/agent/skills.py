"""Skill discovery, loading, and keyword-based auto-selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass
class SkillInfo:
    name: str
    description: str
    skill_file: Path
    content_length: int
    keywords: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Always-loaded skills (coordinator)
# ---------------------------------------------------------------------------

ALWAYS_SKILLS: list[str] = ["inference-optimize"]

# ---------------------------------------------------------------------------
# Keyword -> skill mapping (order preserved for priority)
# ---------------------------------------------------------------------------

CONDITIONAL_SKILLS: dict[str, list[str]] = {
    "model-profiler": [
        "memory", "calculate", "fit", "model", "params", "kv", "weight",
        "profile", "hbm", "utilization", "how much", "can it fit", "size",
    ],
    "benchmark-runner": [
        "benchmark", "run", "docker", "throughput", "vllm", "sglang", "tgi",
        "latency", "serve", "container", "serving", "performance", "test",
    ],
    "hyperloom-session": [
        "kernel", "optimize performance", "hyperloom", "rocm kernel",
        "kernel tuning", "autotuner",
    ],
    "campaign-planner": [
        "compare", "campaign", "cross-framework", "sweep", "multi-config",
        "batch sweep", "tp vs",
    ],
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_skills(skills_dir: Path | str) -> dict[str, SkillInfo]:
    """Walk a skills directory and return a map of skill_name -> SkillInfo."""
    skills_dir = Path(skills_dir)
    skills: dict[str, SkillInfo] = {}
    if not skills_dir.is_dir():
        return skills

    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        name = skill_dir.name
        content = skill_md.read_text(encoding="utf-8", errors="replace")

        # First non-heading, non-empty line as description
        desc = ""
        for line in content.strip().splitlines():
            if line.startswith("#"):
                continue
            stripped = line.strip()
            if stripped:
                desc = stripped[:120]
                break

        keywords = CONDITIONAL_SKILLS.get(name, [])
        skills[name] = SkillInfo(
            name=name,
            description=desc,
            skill_file=skill_md,
            content_length=len(content),
            keywords=keywords,
        )

    return skills


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_skill_content(skill_name: str, *, skills: dict[str, SkillInfo] | None = None, skills_dir: Path | str | None = None) -> str:
    """Return the full SKILL.md text for *skill_name*, or empty string."""
    if skills and skill_name in skills:
        try:
            return skills[skill_name].skill_file.read_text(
                encoding="utf-8", errors="replace"
            )
        except Exception:
            return ""

    if skills_dir:
        skill_md = Path(skills_dir) / skill_name / "SKILL.md"
        if skill_md.exists():
            try:
                return skill_md.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    return ""


# ---------------------------------------------------------------------------
# Auto-selection
# ---------------------------------------------------------------------------

def should_load_skill(skill_name: str, message_text: str) -> bool:
    """Return True if *message_text* contains any keyword for *skill_name*."""
    keywords = CONDITIONAL_SKILLS.get(skill_name, [])
    if not keywords:
        return False
    text_lower = message_text.lower()
    return any(kw in text_lower for kw in keywords)


def select_skills(
    message_text: str,
    explicit_skill: str | None = None,
    extra_always: Sequence[str] = (),
) -> list[str]:
    """Return the ordered list of skill names to load for a given message.

    Priority order:
    1. ALWAYS_SKILLS (coordinator)
    2. Keyword-triggered skills whose keywords match *message_text*
    3. The *explicit_skill* (GUI dropdown) if not already included
    4. *extra_always* skills (caller-specified, e.g. fleet-manager)
    """
    selected: list[str] = list(ALWAYS_SKILLS)

    for name, keywords in CONDITIONAL_SKILLS.items():
        if any(kw in message_text.lower() for kw in keywords):
            if name not in selected:
                selected.append(name)

    if explicit_skill and explicit_skill not in selected:
        selected.append(explicit_skill)

    for s in extra_always:
        if s not in selected:
            selected.append(s)

    return selected
