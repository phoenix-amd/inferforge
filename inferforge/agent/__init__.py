"""Agent module -- agentic loop, tools, skills, system prompt, and metrics extraction."""

from inferforge.agent.loop import run_agent
from inferforge.agent.tools import TOOLS
from inferforge.agent.skills import discover_skills, load_skill_content, should_load_skill
from inferforge.agent.system_prompt import build_system_prompt
from inferforge.agent.metrics_extractor import parse_benchmark_output, extract_gpu_info

__all__ = [
    "run_agent",
    "TOOLS",
    "discover_skills",
    "load_skill_content",
    "should_load_skill",
    "build_system_prompt",
    "parse_benchmark_output",
    "extract_gpu_info",
]
