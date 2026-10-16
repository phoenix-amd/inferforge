"""Hyperloom integration layer for InferForge.

Provides async session management, V6 schema parsing, result import,
recipe syncing, and session monitoring for Hyperloom optimization sessions.
"""

from .cli_wrapper import (
    SessionEvent,
    launch_session,
    cancel_session,
    resume_session,
    get_session_status,
)
from .session_adapter import (
    read_session_breakdown,
    get_session_summary,
    get_session_timeline,
    get_optimization_stack,
    get_measurements,
)
from .v6_parser import (
    parse_v6_metadata,
    parse_v6_task_config,
    parse_v6_outcome,
    parse_v6_graded_axes,
    v6_to_benchmark_run,
    v6_to_hyperloom_session,
    v6_to_recipe,
)
from .result_importer import (
    import_session,
    import_session_batch,
    get_imported_session,
    list_imported_sessions,
)
from .recipe_client import RecipeClient
from .session_monitor import monitor_session, wait_for_session_dir
from .launch_config import (
    campaign_to_hyperloom_args,
    campaign_to_session_matrix,
    build_benchmark_docker_cmd,
)

__all__ = [
    # cli_wrapper
    "SessionEvent",
    "launch_session",
    "cancel_session",
    "resume_session",
    "get_session_status",
    # session_adapter
    "read_session_breakdown",
    "get_session_summary",
    "get_session_timeline",
    "get_optimization_stack",
    "get_measurements",
    # v6_parser
    "parse_v6_metadata",
    "parse_v6_task_config",
    "parse_v6_outcome",
    "parse_v6_graded_axes",
    "v6_to_benchmark_run",
    "v6_to_hyperloom_session",
    "v6_to_recipe",
    # result_importer
    "import_session",
    "import_session_batch",
    "get_imported_session",
    "list_imported_sessions",
    # recipe_client
    "RecipeClient",
    # session_monitor
    "monitor_session",
    "wait_for_session_dir",
    # launch_config
    "campaign_to_hyperloom_args",
    "campaign_to_session_matrix",
    "build_benchmark_docker_cmd",
]
