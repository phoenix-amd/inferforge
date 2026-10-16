"""System prompt builder for the InferForge agent."""

from __future__ import annotations

from pathlib import Path

from inferforge.agent.skills import (
    ALWAYS_SKILLS,
    SkillInfo,
    load_skill_content,
    select_skills,
)

# ---------------------------------------------------------------------------
# Paths (resolved at import time relative to the inferforge package root)
# ---------------------------------------------------------------------------

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent  # inferforge/
_PROJECT_ROOT = _PACKAGE_ROOT.parent                     # inferforge repo root
_CLAUDE_MD = _PROJECT_ROOT / "CLAUDE.md"


# ---------------------------------------------------------------------------
# Run-type instruction blocks
# ---------------------------------------------------------------------------

_RUN_TYPE_INSTRUCTIONS: dict[str, str] = {
    "simulation": (
        "========================================================\n"
        "  RUN TYPE: SIMULATION (memory analysis only)\n"
        "========================================================\n"
        "ALLOWED actions:\n"
        "  1. SSH key discovery\n"
        "  2. GPU detection via rocm-smi / amd-smi\n"
        "  3. Run memory_calculator.py with --json flag\n"
        "  4. Present the full report INCLUDING Section 6b: Batching Optimization\n"
        "     - The JSON output includes a 'batch_sweep' array -- present it as a table\n"
        "     - Show max-num-seqs sweep with chunked prefill ON/OFF comparison\n"
        "     - Include the chunked prefill visual explanation (prefill blocking diagram)\n"
        "     - Label 'Best for latency', 'Best for throughput', 'Balanced'\n\n"
        "FORBIDDEN -- never do these in simulation:\n"
        "  * Searching for model files on disk or NFS\n"
        "  * Checking running Docker containers\n"
        "  * Launching Docker or any container\n"
        "  * Downloading model weights\n"
        "  * Checking HuggingFace cache directories\n"
        "  * Running vLLM, SGLang, or TGI\n\n"
        "If the user mentions 'benchmark' or 'run', clarify that Simulation provides\n"
        "estimated throughput from memory_calculator.py -- not measured numbers.\n"
        "Offer to switch to Real Run for actual benchmarks."
    ),
    "real": (
        "========================================================\n"
        "  RUN TYPE: REAL RUN (actual inference on cluster)\n"
        "========================================================\n"
        "Execute actual Docker + vLLM/SGLang/TGI containers on the cluster.\n\n"
        "MODEL DISCOVERY RULES:\n"
        "  BANNED: find /, find /mnt, find without -maxdepth 3, 'broader search'\n"
        "  ALLOWED: 3 targeted checks (HF cache, NFS models dir, WEKA models dir)\n"
        "  After those 3 checks, STOP. Present options if model not found.\n\n"
        "  In Real Run mode, ALWAYS ask for user confirmation before launching\n"
        "  Docker or running benchmarks -- even in Autonomous mode.\n\n"
        "BATCH SWEEP (after finding best TP, sweep batching params):\n"
        "  1. --max-num-seqs 64  --enable-chunked-prefill   (latency-optimized)\n"
        "  2. --max-num-seqs 128 --disable-chunked-prefill  (throughput-optimized)\n"
        "  3. --max-num-seqs 128 --enable-chunked-prefill   (balanced)\n\n"
        "METRICS TO REPORT (Real Run ONLY -- MEASURED, not estimated):\n"
        "  - TTFT (Time To First Token) -- ms, p50/p90/p99\n"
        "  - TPOT (Time Per Output Token) -- ms, p50/p90/p99\n"
        "  - ITL (Inter-Token Latency) -- ms, p50/p90/p99\n"
        "  - E2E Latency (End-to-End) -- ms, p50/p90/p99\n"
        "  - Throughput -- output tok/s\n"
        "  - Memory utilization -- GB used per GPU\n\n"
        "After parsing benchmark output, call the report_metrics tool to store\n"
        "structured metrics. This is required for dashboard display.\n\n"
        "Present results in a comparison table:\n"
        "  | Config | max-num-seqs | Chunked | Throughput | TTFT p50 | TTFT p99 "
        "| TPOT p50 | ITL p50 | E2E p50 | Rec |\n"
    ),
}

# ---------------------------------------------------------------------------
# Execution mode instruction blocks
# ---------------------------------------------------------------------------

_MODE_INSTRUCTIONS: dict[str, str] = {
    "interactive": (
        "Execution Mode: INTERACTIVE. Before running SSH, Docker, or benchmark "
        "commands, describe what you will do and ask 'Should I proceed?' in the "
        "chat. Wait for the user to confirm."
    ),
    "autonomous": (
        "Execution Mode: AUTONOMOUS. Run the full workflow end-to-end without "
        "asking for confirmation. Proceed immediately through SSH, GPU detection, "
        "memory calculator, Docker launch, and benchmarks.\n\n"
        "ONE EXCEPTION (Real Run only): If the model is NOT an exact match, STOP "
        "and ask the user which option to take."
    ),
    "batch": (
        "Execution Mode: BATCH. Execute the entire task with minimal output. "
        "Report results at the end."
    ),
}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_system_prompt(
    message_text: str,
    skill: str | None = None,
    mode: str = "interactive",
    run_type: str = "simulation",
    *,
    skills_dir: Path | str | None = None,
    skills_map: dict[str, SkillInfo] | None = None,
    project_dir: Path | str | None = None,
) -> str:
    """Assemble the full system prompt for the agent.

    Parameters
    ----------
    message_text:
        The latest user message (used for keyword-based skill loading).
    skill:
        Explicitly selected skill (e.g. from a GUI dropdown).
    mode:
        Execution mode -- interactive, autonomous, or batch.
    run_type:
        simulation or real.
    skills_dir:
        Path to the skills directory. Falls back to inferforge/skills.
    skills_map:
        Pre-built skill map (avoids re-scanning disk).
    project_dir:
        Override for PROJECT_DIR in path constants.
    """
    parts: list[str] = []

    # 1. CLAUDE.md
    if _CLAUDE_MD.exists():
        parts.append(
            _CLAUDE_MD.read_text(encoding="utf-8", errors="replace")
        )

    # 2. Skills
    resolved_skills_dir = Path(skills_dir) if skills_dir else _PACKAGE_ROOT / "skills"
    skill_names = select_skills(message_text, explicit_skill=skill)

    loaded_skills: list[str] = []
    for skill_name in skill_names:
        content = load_skill_content(
            skill_name, skills=skills_map, skills_dir=resolved_skills_dir
        )
        if not content:
            continue

        if skill_name == skill:
            header = "# Active Skill (Selected)"
        elif skill_name not in ALWAYS_SKILLS:
            header = "# Active Skill"
        else:
            header = "# Reference Skill"

        parts.append(f"\n\n{header}: {skill_name}\n\n{content}")
        loaded_skills.append(skill_name)

    # 3. Run type instructions
    parts.append(
        "\n\n"
        + _RUN_TYPE_INSTRUCTIONS.get(run_type, _RUN_TYPE_INSTRUCTIONS["simulation"])
    )

    # 4. Execution mode instructions
    parts.append(
        "\n\n" + _MODE_INSTRUCTIONS.get(mode, _MODE_INSTRUCTIONS["interactive"])
    )

    # 5. Environment context and path constants
    proj = str(project_dir or _PROJECT_ROOT)
    parts.append(
        "\n\nYou are running via a web chat interface, not the Claude CLI terminal. "
        "Use the bash tool for all command execution including SSH. "
        "Format responses with markdown for readability. "
        "The user interacts through a browser -- render results clearly with "
        "tables and code blocks.\n\n"
        "## CRITICAL: Path Constants (use these -- NEVER use git rev-parse)\n\n"
        f"- PROJECT_DIR = `{proj}`\n"
        f"- GPU_SPECS = `{proj}/inferforge/data/gpu_specs.json`\n"
        f"- MODEL_REGISTRY = `{proj}/inferforge/data/model_registry.json`\n"
        f"- MEMORY_CALCULATOR = `{proj}/inferforge/calculator/memory_calculator.py`\n\n"
        "NEVER run `git rev-parse --show-toplevel` -- "
        "the project may not be a git repo in this environment. "
        "Always use the PROJECT_DIR constant above.\n\n"
        "## CRITICAL: SSH Key Discovery\n\n"
        "NEVER assume which SSH key to use. On EVERY new task, first run:\n"
        "```bash\n"
        "for key in ~/.ssh/id_ed25519_moba ~/.ssh/id_ed25519 ~/.ssh/id_rsa; do\n"
        '  [ -f "$key" ] || { echo "KEY_SKIP=$key (file not found)"; continue; }\n'
        '  result=$(ssh -i "$key" -o BatchMode=yes -o ConnectTimeout=10 '
        '-o StrictHostKeyChecking=no <USER>@<HOST> hostname 2>&1)\n'
        "  rc=$?\n"
        "  if [ $rc -eq 0 ]; then\n"
        '    echo "WORKING_KEY=$key HOST=$result"\n'
        "    break\n"
        "  else\n"
        '    echo "KEY_FAIL=$key RC=$rc REASON=$result"\n'
        "  fi\n"
        "done\n"
        "```\n"
        "Use whichever key succeeds. If ALL keys fail, report each KEY_FAIL line "
        "to the user.\n\n"
        "## CRITICAL: Docker Safety\n\n"
        "- ALWAYS use `--rm` on every `docker run`\n"
        "- ALWAYS use `--network=host` (IPv4 forwarding disabled on cluster)\n"
        "- ALWAYS check `docker ps` before starting a new container\n"
        "- ALWAYS use `--device=/dev/kfd --device=/dev/dri --group-add video`\n"
        "- NEVER mount host root into containers\n"
        "- ALWAYS clean up containers after benchmarks: `docker stop <name>`\n\n"
        "## CRITICAL: Progress Messages\n\n"
        "Before EVERY bash tool call that takes more than 2 seconds, emit a text "
        "message like:\n"
        "`Running GPU detection on <node>...`\n"
        "After each completes: `Done -- <one-line result>` or `Failed -- <reason>`\n"
        "Never run two sequential bash calls without a message in between.\n\n"
        "## Structured Metrics Reporting\n\n"
        "After parsing benchmark output, ALWAYS call the `report_metrics` tool to "
        "store structured metrics. This enables the dashboard to display results "
        "without regex parsing. Include all available fields.\n"
    )

    return "\n\n---\n\n".join(parts)
