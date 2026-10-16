"""Skill discovery and content routes."""

from fastapi import APIRouter, HTTPException

from inferforge.config import SKILLS, load_skill_content

router = APIRouter(prefix="/api", tags=["skills"])


@router.get("/skills")
def api_list_skills():
    return list(SKILLS.values())


@router.get("/skills/{name}")
def api_get_skill(name: str):
    if name not in SKILLS:
        raise HTTPException(404, f"Skill '{name}' not found")
    content = load_skill_content(name)
    return {
        **SKILLS[name],
        "content": content,
    }
