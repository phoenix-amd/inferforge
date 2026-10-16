"""Database schema -- all 12 tables for InferForge."""

from .connection import get_connection

_SCHEMA_SQL = """
-- 1. users
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT,
    role            TEXT NOT NULL DEFAULT 'user',
    api_key_hash    TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    last_login      TEXT
);

-- 2. projects
CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    owner_id        TEXT NOT NULL,
    description     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 3. project_members
CREATE TABLE IF NOT EXISTS project_members (
    project_id      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    PRIMARY KEY (project_id, user_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)    REFERENCES users(id)    ON DELETE CASCADE
);

-- 4. conversations
CREATE TABLE IF NOT EXISTS conversations (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    skill           TEXT DEFAULT NULL,
    mode            TEXT DEFAULT 'interactive',
    project_id      TEXT DEFAULT NULL,
    user_id         TEXT DEFAULT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id)    REFERENCES users(id)    ON DELETE SET NULL
);

-- 5. messages
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    tool_calls      TEXT DEFAULT NULL,
    tool_results    TEXT DEFAULT NULL,
    metadata        TEXT DEFAULT NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

-- 6. benchmark_runs
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id                      TEXT PRIMARY KEY,
    conversation_id         TEXT,
    campaign_id             TEXT,
    hyperloom_session_id    TEXT,
    model_name              TEXT NOT NULL,
    model_hf_id             TEXT,
    model_params_b          REAL,
    model_architecture      TEXT,
    gpu_platform            TEXT NOT NULL,
    gpu_count               INTEGER NOT NULL DEFAULT 1,
    framework               TEXT NOT NULL DEFAULT 'vllm',
    framework_version       TEXT,
    tp                      INTEGER NOT NULL DEFAULT 1,
    pp                      INTEGER NOT NULL DEFAULT 1,
    dp                      INTEGER NOT NULL DEFAULT 1,
    ep                      INTEGER NOT NULL DEFAULT 0,
    weight_dtype            TEXT NOT NULL DEFAULT 'bf16',
    kv_dtype                TEXT,
    seq_len                 INTEGER,
    input_len               INTEGER,
    output_len              INTEGER,
    batch_size              INTEGER,
    max_num_seqs            INTEGER,
    chunked_prefill         INTEGER DEFAULT 0,
    ttft_p50                REAL,
    ttft_p90                REAL,
    ttft_p99                REAL,
    ttft_mean               REAL,
    tpot_p50                REAL,
    tpot_p90                REAL,
    tpot_p99                REAL,
    itl_p50                 REAL,
    itl_p90                 REAL,
    itl_p99                 REAL,
    e2e_p50                 REAL,
    e2e_p90                 REAL,
    e2e_p99                 REAL,
    throughput_tps          REAL,
    throughput_rps          REAL,
    hbm_used_gb             REAL,
    hbm_util_pct            REAL,
    run_mode                TEXT DEFAULT 'autonomous',
    evidence_source         TEXT,
    raw_output_path         TEXT,
    config_json             TEXT,
    created_at              TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL,
    FOREIGN KEY (campaign_id)     REFERENCES campaigns(id)     ON DELETE SET NULL
);

-- 7. campaigns
CREATE TABLE IF NOT EXISTS campaigns (
    id                          TEXT PRIMARY KEY,
    project_id                  TEXT,
    user_id                     TEXT,
    name                        TEXT NOT NULL,
    description                 TEXT,
    status                      TEXT NOT NULL DEFAULT 'draft',
    model_name                  TEXT,
    model_hf_id                 TEXT,
    input_len                   INTEGER,
    output_len                  INTEGER,
    num_prompts                 INTEGER,
    request_rate                REAL,
    frameworks                  TEXT,
    topologies                  TEXT,
    dtypes                      TEXT,
    gpu_platforms               TEXT,
    sla_ttft_p95_ms             REAL,
    sla_ttft_p99_ms             REAL,
    sla_tpot_p99_ms             REAL,
    sla_throughput_floor_tps    REAL,
    max_gpu_hours               REAL,
    max_wall_hours              REAL,
    winner_run_id               TEXT,
    summary_json                TEXT,
    created_at                  TEXT DEFAULT (datetime('now')),
    updated_at                  TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id)    REFERENCES projects(id)       ON DELETE SET NULL,
    FOREIGN KEY (user_id)       REFERENCES users(id)          ON DELETE SET NULL,
    FOREIGN KEY (winner_run_id) REFERENCES benchmark_runs(id) ON DELETE SET NULL
);

-- 8. fleet_nodes
CREATE TABLE IF NOT EXISTS fleet_nodes (
    id              TEXT PRIMARY KEY,
    hostname        TEXT NOT NULL UNIQUE,
    ip_address      TEXT,
    ssh_user        TEXT,
    ssh_key_path    TEXT,
    gpu_platform    TEXT,
    gpu_count       INTEGER DEFAULT 0,
    hbm_per_gpu_gb  REAL DEFAULT 0,
    rocm_version    TEXT,
    status          TEXT NOT NULL DEFAULT 'unknown',
    last_probed     TEXT,
    metadata_json   TEXT
);

-- 9. fleet_reservations
CREATE TABLE IF NOT EXISTS fleet_reservations (
    id              TEXT PRIMARY KEY,
    node_id         TEXT NOT NULL,
    campaign_id     TEXT,
    conversation_id TEXT,
    gpu_start       INTEGER NOT NULL DEFAULT 0,
    gpu_count       INTEGER NOT NULL DEFAULT 1,
    reserved_at     TEXT DEFAULT (datetime('now')),
    expires_at      TEXT,
    released_at     TEXT,
    FOREIGN KEY (node_id)         REFERENCES fleet_nodes(id)   ON DELETE CASCADE,
    FOREIGN KEY (campaign_id)     REFERENCES campaigns(id)     ON DELETE SET NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);

-- 10. hyperloom_sessions
CREATE TABLE IF NOT EXISTS hyperloom_sessions (
    id                  TEXT PRIMARY KEY,
    campaign_id         TEXT,
    conversation_id     TEXT,
    claw_session_id     TEXT,
    session_dir         TEXT,
    host                TEXT,
    model_name          TEXT,
    model_path          TEXT,
    framework_name      TEXT,
    gpu_type            TEXT,
    tp                  INTEGER,
    ep                  INTEGER,
    precision           TEXT,
    stop_reason         TEXT,
    outcome_gain_pct    REAL,
    outcome_json        TEXT,
    schema_version      TEXT,
    timeline_json       TEXT,
    started_at          TEXT,
    ended_at            TEXT,
    elapsed_minutes     REAL,
    imported_at         TEXT DEFAULT (datetime('now')),
    breakdown_path      TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    FOREIGN KEY (campaign_id)     REFERENCES campaigns(id)     ON DELETE SET NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);

-- 11. recipes
CREATE TABLE IF NOT EXISTS recipes (
    id                  TEXT PRIMARY KEY,
    model_family        TEXT,
    model_name          TEXT NOT NULL,
    gpu_type            TEXT NOT NULL,
    framework           TEXT NOT NULL DEFAULT 'vllm',
    optimizations_json  TEXT,
    server_args         TEXT,
    kernel_patches_json TEXT,
    baseline_tps        REAL,
    optimized_tps       REAL,
    gain_pct            REAL,
    source              TEXT,
    source_session_id   TEXT,
    kb_record_id        TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- 12. deployments
CREATE TABLE IF NOT EXISTS deployments (
    id                          TEXT PRIMARY KEY,
    project_id                  TEXT,
    benchmark_run_id            TEXT,
    recipe_id                   TEXT,
    model_name                  TEXT NOT NULL,
    framework                   TEXT NOT NULL DEFAULT 'vllm',
    node_id                     TEXT,
    tp                          INTEGER NOT NULL DEFAULT 1,
    pp                          INTEGER NOT NULL DEFAULT 1,
    dp                          INTEGER NOT NULL DEFAULT 1,
    launch_config_json          TEXT,
    state                       TEXT NOT NULL DEFAULT 'pending',
    canary_pct                  REAL DEFAULT 0,
    sla_ttft_p99_ms             REAL,
    sla_throughput_floor_tps    REAL,
    created_at                  TEXT DEFAULT (datetime('now')),
    deployed_at                 TEXT,
    promoted_at                 TEXT,
    stopped_at                  TEXT,
    FOREIGN KEY (project_id)       REFERENCES projects(id)       ON DELETE SET NULL,
    FOREIGN KEY (benchmark_run_id) REFERENCES benchmark_runs(id) ON DELETE SET NULL,
    FOREIGN KEY (recipe_id)        REFERENCES recipes(id)        ON DELETE SET NULL,
    FOREIGN KEY (node_id)          REFERENCES fleet_nodes(id)    ON DELETE SET NULL
);
"""

_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_msg_conv           ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conv_project       ON conversations(project_id);
CREATE INDEX IF NOT EXISTS idx_conv_user          ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_bench_conv         ON benchmark_runs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_bench_campaign     ON benchmark_runs(campaign_id);
CREATE INDEX IF NOT EXISTS idx_bench_model        ON benchmark_runs(model_name);
CREATE INDEX IF NOT EXISTS idx_bench_gpu          ON benchmark_runs(gpu_platform);
CREATE INDEX IF NOT EXISTS idx_campaign_project   ON campaigns(project_id);
CREATE INDEX IF NOT EXISTS idx_campaign_status    ON campaigns(status);
CREATE INDEX IF NOT EXISTS idx_fleet_hostname     ON fleet_nodes(hostname);
CREATE INDEX IF NOT EXISTS idx_fleet_status       ON fleet_nodes(status);
CREATE INDEX IF NOT EXISTS idx_reservation_node   ON fleet_reservations(node_id);
CREATE INDEX IF NOT EXISTS idx_reservation_exp    ON fleet_reservations(expires_at);
CREATE INDEX IF NOT EXISTS idx_hloom_campaign     ON hyperloom_sessions(campaign_id);
CREATE INDEX IF NOT EXISTS idx_hloom_status       ON hyperloom_sessions(status);
CREATE INDEX IF NOT EXISTS idx_recipe_model       ON recipes(model_name);
CREATE INDEX IF NOT EXISTS idx_recipe_gpu         ON recipes(gpu_type);
CREATE INDEX IF NOT EXISTS idx_deploy_project     ON deployments(project_id);
CREATE INDEX IF NOT EXISTS idx_deploy_state       ON deployments(state);
CREATE INDEX IF NOT EXISTS idx_deploy_node        ON deployments(node_id);
CREATE INDEX IF NOT EXISTS idx_projmem_user       ON project_members(user_id);
"""


def init_db(db_path: str | None = None) -> None:
    """Create all tables and indexes. Safe to call repeatedly (IF NOT EXISTS)."""
    conn = get_connection(db_path)
    conn.executescript(_SCHEMA_SQL)
    conn.executescript(_INDEX_SQL)
