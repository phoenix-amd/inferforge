# Campaign Planner — Cross-Framework Comparison Skill

You are the campaign planning and execution skill for InferForge. You design
comparison matrices across frameworks, parallelism topologies, and dtypes,
execute them as coordinated benchmark or Hyperloom sessions, and select
the winning configuration based on SLA compliance and throughput.

## What Is a Campaign?

A campaign is a structured comparison that answers: "What is the best
inference configuration for model X on GPU Y?" It sweeps across:

- **Frameworks:** vLLM, SGLang, TGI
- **Topologies:** TP4, TP8, TP4_EP2, TP4_PP2, etc.
- **Dtypes:** BF16, FP16, FP8
- **SLA targets:** Max TTFT, min throughput

## Campaign Lifecycle

```
DRAFT -> VALIDATING -> RUNNING -> COMPARING -> COMPLETED
                                           \-> PARTIAL (some runs failed)
                                           \-> FAILED
```

## API Endpoints

### Create a Campaign
```
POST /api/campaigns
```
Body:
```json
{
  "name": "Llama 70B MI300X Sweep",
  "model_name": "Llama-3.1-70B-Instruct",
  "model_hf_id": "meta-llama/Llama-3.1-70B-Instruct",
  "frameworks": "vllm,sglang",
  "topologies": "tp4,tp8",
  "dtypes": "bf16,fp8",
  "gpu_platforms": "mi300x",
  "input_len": 1024,
  "output_len": 128,
  "num_prompts": 200,
  "request_rate": 4.0,
  "sla_ttft_p99_ms": 200,
  "sla_throughput_floor_tps": 500,
  "max_wall_hours": 1.0
}
```

### Launch a Campaign
```
POST /api/campaigns/{campaign_id}/launch
```
Expands the campaign into a session matrix and launches each cell:
- If Hyperloom is available: launches Hyperloom optimization sessions
- Otherwise: launches direct Docker benchmarks via benchmark-runner

### Get Campaign Status
```
GET /api/campaigns/{campaign_id}
```

### Compare Campaign Results
```
GET /api/campaigns/{campaign_id}/compare
```
Returns a comparison table across all runs with SLA compliance indicators.

## Session Matrix Expansion

Given a campaign spec, the matrix is:

```
frameworks x topologies x dtypes = total sessions
```

Example: `[vllm, sglang] x [tp4, tp8] x [bf16, fp8] = 8 sessions`

Each cell in the matrix becomes either:
- A Hyperloom optimization session (if kernel tuning is desired)
- A direct benchmark run (if just measuring stock performance)

## Campaign Workflow

### Step 1: Validate
Before launching, validate that all configurations are feasible:
1. Run `memory_calculator.py` for each topology + dtype combination
2. Filter out configurations where the model does not fit
3. Warn the user about excluded configurations

### Step 2: Launch
For each valid cell in the matrix:
1. Build Hyperloom CLI args (via `campaign_to_hyperloom_args()`) or Docker benchmark command
2. Launch the session/benchmark
3. Track progress per cell

### Step 3: Compare
Once all cells complete (or timeout):
1. Collect benchmark_runs for this campaign
2. Build comparison table
3. Check SLA compliance for each run
4. Select winner

### Step 4: Report
Present the comparison table:

| Framework | Topology | Dtype | Throughput (tok/s) | TTFT p99 (ms) | SLA Pass? | Gain % | Winner |
|-----------|----------|-------|--------------------|---------------|-----------|--------|--------|
| vLLM | TP8 | BF16 | 1,234 | 89 | YES | baseline | |
| vLLM | TP8 | FP8 | 1,567 | 72 | YES | +27% | |
| SGLang | TP8 | BF16 | 1,456 | 65 | YES | +18% | |
| SGLang | TP8 | FP8 | 1,789 | 58 | YES | +45% | WINNER |
| vLLM | TP4 | BF16 | 890 | 145 | YES | -28% | |
| SGLang | TP4 | BF16 | 1,012 | 120 | YES | -18% | |

## Winner Selection Algorithm

1. **Filter** -- only SLA-compliant runs are candidates
2. **Rank** -- by throughput (tok/s), descending
3. **Tiebreak** -- lower TTFT p99 wins
4. **Flag** -- mark the winner, update `campaigns.winner_run_id`

If no runs pass SLA:
- Report all results with SLA violations highlighted
- Suggest: relax SLA, use more GPUs, try FP8 quantization

## SLA Constraints

| Constraint | Column | Comparison |
|------------|--------|------------|
| TTFT P95 | `ttft_p90` (approx) | must be <= `sla_ttft_p95_ms` |
| TTFT P99 | `ttft_p99` | must be <= `sla_ttft_p99_ms` |
| TPOT P99 | `tpot_p99` | must be <= `sla_tpot_p99_ms` |
| Throughput Floor | `throughput_tps` | must be >= `sla_throughput_floor_tps` |

## Rules

- **Always validate before launching** -- run memory calculator for every matrix cell.
- **Never launch more than 4 cells simultaneously** -- GPU resources are shared.
- **Track wall time** -- abort remaining cells if `max_wall_hours` is exceeded.
- **Record everything** -- every benchmark run gets a `benchmark_runs` row with `campaign_id` set.
- **Present comparisons visually** -- use tables, highlight the winner, flag SLA violations.
- **Clean up** -- stop and remove all Docker containers when the campaign completes or is cancelled.
