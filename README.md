<p align="center">
  <img src="https://img.shields.io/badge/AMD-Instinct_MI300X%2FMI325X%2FMI350X-ED1C24?style=for-the-badge&logo=amd&logoColor=white" />
  <img src="https://img.shields.io/badge/ROCm-6.x-76B900?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Claude_Code-Agent_Powered-5A67D8?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
</p>

<h1 align="center">
  InferForge
</h1>

<h3 align="center">
  AMD Unified Inference Optimization Platform
</h3>

<p align="center">
  <b>The missing layer between profiling and production.</b><br/>
  Combines autonomous AI agents, real-time GPU fleet management, kernel-level optimization,<br/>
  and production deployment — in a single conversational platform for AMD Instinct GPUs.
</p>

<p align="center">
  <a href="#executive-summary">Executive Summary</a> &bull;
  <a href="#the-problem">The Problem</a> &bull;
  <a href="#the-solution">The Solution</a> &bull;
  <a href="#gap-analysis">Gap Analysis</a> &bull;
  <a href="#architecture">Architecture</a> &bull;
  <a href="#features">Features</a> &bull;
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#api-reference">API Reference</a>
</p>

---

## Executive Summary

| Metric | Impact |
|--------|--------|
| **Time to first benchmark** | Minutes, not hours — natural language drives the full workflow |
| **Optimization coverage** | End-to-end: memory profiling → benchmarking → kernel optimization → production deployment |
| **Model support** | 50+ LLMs pre-configured (Llama, Qwen, DeepSeek, Mixtral, Phi, Gemma, DBRX, Falcon, etc.) |
| **GPU platforms** | MI250X, MI300X, MI308X, MI325X, MI350X, MI355X, MI450X, MI455X, Helios |
| **Frameworks** | vLLM, SGLang, TGI — side-by-side comparison with SLA-based winner selection |
| **Fleet visibility** | Real-time GPU telemetry (utilization, temperature, power) across all cluster nodes |
| **Optimization gains** | Hyperloom integration delivers 15-40%+ throughput improvement via kernel + framework tuning |
| **Deployment pipeline** | Canary → Promoted → Rollback with traffic management — no manual Docker commands |

---

## The Problem

Getting an LLM to serve optimally on AMD Instinct GPUs today requires **three separate workflows**, each with its own tools, skills, and gaps:

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                        THE FRAGMENTED INFERENCE WORKFLOW                             │
│                                                                                     │
│  ┌──────────────┐     ┌──────────────────┐     ┌────────────────────┐               │
│  │  PROFILING    │     │  OPTIMIZATION    │     │  DEPLOYMENT        │               │
│  │              │     │                  │     │                    │               │
│  │  "Will this  │     │  "How do I make  │     │  "How do I get    │               │
│  │   model fit  │ ──► │   it faster?"    │ ──► │   this to prod?"  │               │
│  │   on my      │     │                  │     │                    │               │
│  │   GPUs?"     │     │  Manual Docker,  │     │  Manual deploy,   │               │
│  │              │     │  trial & error,  │     │  no canary,       │               │
│  │  Spreadsheet │     │  no kernel       │     │  no rollback,     │               │
│  │  math,       │     │  optimization    │     │  no fleet view    │               │
│  │  guesswork   │     │                  │     │                    │               │
│  └──────────────┘     └──────────────────┘     └────────────────────┘               │
│                                                                                     │
│  ❌ No unified tool     ❌ Different CLIs      ❌ No state machine                   │
│  ❌ No agent automation ❌ No recipe system     ❌ No GPU reservation                 │
│  ❌ No fleet visibility ❌ No SLA tracking      ❌ No comparison data                 │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### Today's tools each solve ONE piece:

| Tool | What It Does | What It Doesn't Do |
|------|-------------|-------------------|
| **[Hyperloom](https://github.com/AMD-AGI/Hyperloom)** | Autonomous kernel + framework optimization via multi-agent AI | No GUI, no fleet management, no deployment pipeline, no pre-benchmark memory analysis, no campaign comparison |
| **[AMD Inference Agent](https://github.com/phoenix-amd/amd-inference-agent)** | Conversational AI agent for GPU detection, memory profiling, Docker benchmarks | No kernel optimization, no deployment pipeline, no recipe system, no fleet management, no campaigns |
| **Manual workflow** | SSH + Docker + spreadsheets | Everything is manual, error-prone, and doesn't scale |

**An engineer shouldn't need three tools and a spreadsheet to go from "which GPU config?" to "serving in production."**

---

## The Solution

**InferForge** unifies the entire inference optimization lifecycle into a single AI-powered platform. It combines the **conversational intelligence** of AMD Inference Agent with the **deep kernel optimization** of Hyperloom — and adds the missing layers: fleet management, campaign comparison, deployment pipeline, and a real-time mission control GUI.

```
You:    "Optimize Llama 3.1 70B on 8x MI300X with vLLM"

InferForge:
        1. Detects GPUs via SSH (amd-smi) ───────────────── 30 sec
        2. Calculates memory: weights + KV cache + overhead  instant
        3. Selects valid TP configs (TP=4, TP=8) ──────────  instant
        4. Creates Hyperloom session ───────────────────────  instant
        5. Runs PRELUDE baseline (vanilla vLLM) ───────────  ~15 min
        6. ENABLEMENT: toggles framework features ─────────  ~10 min
        7. FRAMEWORK_AGENT: tunes server args ─────────────  ~30 min
        8. KERNEL_AGENT: optimizes GPU kernels ────────────  ~45 min
        9. SWEEP: measures across concurrency levels ──────  ~20 min
       10. Reports: "32% throughput gain, recipe saved" ───  instant
       11. Deploys optimized config as canary (10%) ───────  2 min
       12. Promotes to production (100%) ──────────────────  1 click
```

---

## Gap Analysis — Why InferForge Exists

InferForge was born from identifying the gaps in both Hyperloom and AMD Inference Agent, then building a platform that **covers both** while adding critical missing capabilities.

### Feature Comparison Matrix

| Capability | Hyperloom | AMD Inference Agent | InferForge |
|:-----------|:---:|:---:|:---:|
| **Pre-Benchmark Analysis** | | | |
| Memory profiling (weight + KV cache) | — | ✅ (9 models) | ✅ **(50+ models)** |
| MLA-aware KV cache (DeepSeek) | — | — | ✅ |
| MoE-aware expert memory | — | — | ✅ |
| Parallelism table (TP/PP/DP/EP) | — | ✅ | ✅ |
| HBM utilization visualization | — | ✅ | ✅ |
| Batch size capacity analysis | — | ✅ (calc only) | ✅ **(calc + real)** |
| | | | |
| **Benchmarking** | | | |
| vLLM benchmark | ✅ | ✅ | ✅ |
| SGLang benchmark | ✅ | ✅ | ✅ |
| TGI benchmark | — | ✅ | ✅ |
| 3-config sweep (latency/throughput/balanced) | — | — | ✅ |
| Structured metrics DB | — | Regex extraction | ✅ **(40+ field schema)** |
| | | | |
| **Optimization** | | | |
| Framework arg tuning | ✅ | — | ✅ **(via Hyperloom)** |
| Kernel-level optimization (GEAK/KernelForge) | ✅ | — | ✅ **(via Hyperloom)** |
| Multi-agent orchestration (Orchestrator + Critic) | ✅ | — | ✅ **(via Hyperloom)** |
| Roofline-driven headroom analysis | ✅ | — | ✅ **(via Hyperloom)** |
| Recipe knowledge base | ✅ | — | ✅ **(+ REST API)** |
| | | | |
| **Campaign & Comparison** | | | |
| Multi-framework comparison (vLLM vs SGLang) | — | — | ✅ |
| Multi-topology comparison (TP=4 vs TP=8) | — | — | ✅ |
| SLA-based winner selection | — | — | ✅ |
| Campaign management API | — | — | ✅ |
| | | | |
| **Fleet Management** | | | |
| Node inventory | — | — | ✅ |
| Live GPU telemetry (util/temp/power) | — | — | ✅ |
| GPU reservation system | — | — | ✅ |
| Node health probe (SSH) | — | — | ✅ |
| Stale container detection + cleanup | — | — | ✅ |
| Node recovery (aggressive cleanup) | — | — | ✅ |
| Preflight health checks (RAM, GPU, platform) | — | — | ✅ |
| | | | |
| **Deployment** | | | |
| Canary deployment (gradual rollout) | — | — | ✅ |
| Promote to production | — | — | ✅ |
| Rollback capability | — | — | ✅ |
| Deployment state machine | — | — | ✅ |
| Launch config serialization | — | — | ✅ |
| | | | |
| **User Experience** | | | |
| Web GUI / Dashboard | — | Basic chat UI | ✅ **(Mission Control)** |
| Real-time WebSocket streaming | — | ✅ | ✅ |
| Optimization timeline (Gantt chart) | — | — | ✅ |
| GPU telemetry heatmap | — | — | ✅ |
| Benchmark result charts | — | — | ✅ |
| Deployment pipeline visualization | — | — | ✅ |
| | | | |
| **Platform** | | | |
| REST API (50+ endpoints) | — | 5 endpoints | ✅ **(50+ endpoints)** |
| JWT authentication | — | Basic Auth | ✅ |
| Multi-user support | — | — | ✅ |
| SQLite DB (12 tables, 20+ indexes) | — | 1 table | ✅ |
| AI agent with tool execution | ✅ (CLI) | ✅ | ✅ |
| 3 execution modes (Interactive/Autonomous/Batch) | — | ✅ | ✅ |
| Model weight discovery (3-path search) | — | Abort if missing | ✅ |

### The Gap Visualization

```
                    Hyperloom                          AMD Inference Agent
              ┌────────────────────┐              ┌────────────────────────┐
              │                    │              │                        │
              │  Kernel Opt ✅     │              │  Memory Profiling ✅   │
              │  Framework Tune ✅ │              │  GPU Detection ✅      │
              │  Recipe KB ✅      │              │  Docker Benchmark ✅   │
              │  Multi-Agent ✅    │              │  Conversational AI ✅  │
              │  Roofline ✅       │              │  3 Execution Modes ✅  │
              │                    │              │                        │
              │  ❌ No GUI          │              │  ❌ No Optimization     │
              │  ❌ No Fleet Mgmt   │              │  ❌ No Campaigns        │
              │  ❌ No Campaigns    │              │  ❌ No Deployment       │
              │  ❌ No Deployment   │              │  ❌ No Fleet Mgmt      │
              │  ❌ No Memory Calc  │              │  ❌ No Recipes          │
              │  ❌ No REST API     │              │  ❌ No MLA KV Cache     │
              │  ❌ No Auth         │              │  ❌ Limited Models (9)  │
              │                    │              │                        │
              └─────────┬──────────┘              └───────────┬────────────┘
                        │                                     │
                        │         ┌───────────────┐           │
                        └────────►│  InferForge   │◄──────────┘
                                  │               │
                                  │  ALL of the   │
                                  │  above, PLUS: │
                                  │               │
                                  │  ✅ Mission    │
                                  │    Control GUI │
                                  │  ✅ Fleet Mgmt │
                                  │  ✅ Campaigns  │
                                  │  ✅ Deployment │
                                  │  ✅ 50+ Models │
                                  │  ✅ 50+ APIs   │
                                  │  ✅ MLA/MoE    │
                                  │  ✅ JWT Auth   │
                                  │  ✅ Telemetry  │
                                  │  ✅ 12-Table DB│
                                  └───────────────┘
```

---

## Architecture

### System Overview

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│                              InferForge Platform                                  │
│                                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  ┌───────────────┐  │
│  │              ERA — Mission Control GUI                    │  │  REST API     │  │
│  │                                                          │  │  50+ endpts   │  │
│  │  ┌──────────────┐  ┌──────────────────┐                  │  │               │  │
│  │  │ GPU Telemetry │  │ Optimization     │                  │  │  /api/fleet   │  │
│  │  │ Heatmap      │  │ Timeline (Gantt) │                  │  │  /api/bench   │  │
│  │  │ Live util/   │  │ PRELUDE →        │                  │  │  /api/deploy  │  │
│  │  │ temp/power   │  │ ENABLEMENT →     │                  │  │  /api/hyper   │  │
│  │  │              │  │ FRAMEWORK →      │                  │  │  /api/recipe  │  │
│  │  │              │  │ KERNEL → SWEEP   │                  │  │  /api/camp    │  │
│  │  └──────────────┘  └──────────────────┘                  │  │  /api/calc    │  │
│  │  ┌──────────────┐  ┌──────────────────┐                  │  │  /api/auth    │  │
│  │  │ Benchmark    │  │ Deployment       │  ┌────────────┐  │  │               │  │
│  │  │ Results      │  │ Pipeline         │  │  COMMAND   │  │  │  WebSocket    │  │
│  │  │ Charts +     │  │ pending →        │  │  SIDEBAR   │  │  │  /ws/chat     │  │
│  │  │ Metric Cards │  │ canary →         │  │  Chat +    │  │  │  /ws/hyper    │  │
│  │  │ Throughput,  │  │ promoted →       │  │  Config +  │  │  │  /ws/fleet    │  │
│  │  │ TTFT, ITL    │  │ (or rollback)    │  │  Quick Cmd │  │  │               │  │
│  │  └──────────────┘  └──────────────────┘  └────────────┘  │  └───────────────┘  │
│  └──────────────────────────────────────────────────────────┘                      │
│                                    │                                               │
│                        ┌───────────▼───────────┐                                   │
│                        │   FastAPI Server       │                                   │
│                        │   (Port 7801)          │                                   │
│                        │                       │                                   │
│                        │   11 API Routers      │                                   │
│                        │   WebSocket Hub       │                                   │
│                        │   JWT Auth Layer      │                                   │
│                        │   Agent Loop          │                                   │
│                        └───┬─────┬─────┬───────┘                                   │
│                            │     │     │                                           │
│              ┌─────────────┤     │     ├─────────────┐                             │
│              ▼             ▼     │     ▼             ▼                             │
│  ┌──────────────┐ ┌────────────┐ │ ┌──────────┐ ┌──────────┐                      │
│  │   SQLite DB  │ │  Claude AI │ │ │  GPU     │ │ Hyperloom│                      │
│  │   12 tables  │ │  Agent     │ │ │  Cluster │ │ Engine   │                      │
│  │   20+ indexes│ │  6 skills  │ │ │  (SSH)   │ │ (Docker) │                      │
│  │              │ │  4 tools   │ │ │          │ │          │                      │
│  │  users       │ │  streaming │ │ │  amd-smi │ │ PRELUDE  │                      │
│  │  benchmarks  │ │  3 modes   │ │ │  rocm-smi│ │ ENABLE   │                      │
│  │  campaigns   │ │            │ │ │  telemetry│ │ FW_AGENT │                      │
│  │  deployments │ └────────────┘ │ │          │ │ KN_AGENT │                      │
│  │  fleet_nodes │                │ │  vLLM    │ │ SWEEP    │                      │
│  │  sessions    │                │ │  SGLang  │ │ CLOSE    │                      │
│  │  recipes     │                │ │  TGI     │ │          │                      │
│  └──────────────┘                │ └──────────┘ └──────────┘                      │
│                                  │                                                 │
│                    ┌─────────────▼──────────────┐                                  │
│                    │   Memory Calculator Engine  │                                  │
│                    │                             │                                  │
│                    │   engine.py + kv_cache.py   │                                  │
│                    │   + batch_sweep.py          │                                  │
│                    │                             │                                  │
│                    │   50+ models  ×  8 GPUs     │                                  │
│                    │   MHA / GQA / MLA support   │                                  │
│                    │   MoE expert distribution   │                                  │
│                    └─────────────────────────────┘                                  │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### End-to-End Optimization Flow

```
┌─────────┐    ┌──────────────┐    ┌───────────────────┐    ┌──────────────────┐    ┌─────────────┐
│  INPUT  │    │  PROFILING   │    │   OPTIMIZATION     │    │  COMPARISON      │    │ DEPLOYMENT  │
│         │    │              │    │                    │    │                  │    │             │
│ Model   │    │ GPU Detect   │    │ Hyperloom Session  │    │ Campaign         │    │ Canary      │
│ name,   │───►│ (amd-smi)    │───►│                    │───►│ System           │───►│ (10%)       │
│ GPU     │    │              │    │ PRELUDE            │    │                  │    │     │       │
│ cluster,│    │ Memory Calc  │    │   Baseline perf    │    │ vLLM vs SGLang   │    │     ▼       │
│ natural │    │ (engine.py)  │    │                    │    │ TP=4 vs TP=8     │    │ Promoted    │
│ language│    │              │    │ ENABLEMENT         │    │ bf16 vs fp8      │    │ (100%)      │
│         │    │ Parallelism  │    │   Feature flags    │    │                  │    │     │       │
│         │    │ Table        │    │                    │    │ SLA Evaluation:  │    │     ▼       │
│         │    │ (TP/PP/DP)   │    │ FRAMEWORK_AGENT    │    │ ✅ TTFT < 100ms  │    │ Or:         │
│         │    │              │    │   Server arg tune  │    │ ✅ Tput > 2000   │    │ Rollback    │
│         │    │ HBM Visual   │    │                    │    │ ✅ TPOT < 15ms   │    │             │
│         │    │              │    │ KERNEL_AGENT       │    │                  │    │ Recipe      │
│         │    │ Batch Size   │    │   GPU kernel opt   │    │ Winner:          │    │ saved to    │
│         │    │ Analysis     │    │   (GEAK/Triton)    │    │ "vLLM TP=8 fp8" │    │ Knowledge   │
│         │    │              │    │                    │    │                  │    │ Base        │
│         │    │              │    │ SWEEP              │    │                  │    │             │
│         │    │              │    │   Concurrency test │    │                  │    │             │
│         │    │              │    │                    │    │                  │    │             │
│         │    │              │    │ CLOSE              │    │                  │    │             │
│         │    │              │    │   Recipe export    │    │                  │    │             │
└─────────┘    └──────────────┘    └───────────────────┘    └──────────────────┘    └─────────────┘
     │                │                      │                       │                     │
     │          ┌─────▼──────────────────────▼───────────────────────▼─────────────────────▼──┐
     │          │                    ERA — Mission Control Dashboard                          │
     └─────────►│   Real-time visualization of every stage across all fleet nodes             │
                └────────────────────────────────────────────────────────────────────────────┘
```

### Hyperloom Integration — Multi-Agent Kernel Optimization

InferForge wraps and extends [ROCm Hyperloom](https://github.com/AMD-AGI/Hyperloom) with session lifecycle management, real-time UI monitoring, and automated recipe extraction:

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│                     HYPERLOOM OPTIMIZATION ENGINE                                 │
│                     (Orchestrated by InferForge)                                  │
│                                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐  │
│  │                        Workload Profiling                                   │  │
│  │                                                                             │  │
│  │    TraceLens Agent                                                          │  │
│  │    ├── IntelliKit ──── Low-level GPU Profiling                              │  │
│  │    ├── Magpie ──────── Trace Collection + Benchmark                         │  │
│  │    └── TraceLens ───── Trace Analysis + Roofline Model                      │  │
│  │                  │                                                          │  │
│  │                  ▼                                                          │  │
│  │    Gap Analysis and Bridge Planning                                         │  │
│  └─────────────────────────────────────────────────────────────────────────────┘  │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐  │
│  │               Kernel + Self-Evolving Optimization                           │  │
│  │                                                                             │  │
│  │    Arbor — Self-Evolving Optimization Search                                │  │
│  │    ┌──────────────────────────────────────────────┐                          │  │
│  │    │  Agent Loop: Think → Decide → Implement →    │                          │  │
│  │    │              Benchmark → Validate            │                          │  │
│  │    │              ↕                               │                          │  │
│  │    │  Dynamic Specialist Agent + Knowledge Base   │                          │  │
│  │    └──────────────────────────────────────────────┘                          │  │
│  │                                                                             │  │
│  │    Kernel Optimization Agents                                               │  │
│  │    ├── GEAK ─────────── GPU kernel generation (Triton/HIP/FlyDSL)           │  │
│  │    ├── KernelForge ──── Built-in kernel optimizer                           │  │
│  │    ├── ClaudeCode ───── AI-driven source patches                            │  │
│  │    └── OpenAI Codex ─── Alternative AI backend                              │  │
│  └─────────────────────────────────────────────────────────────────────────────┘  │
│                                    │                                               │
│                                    ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────┐  │
│  │                         Apply Changes                                       │  │
│  │                                                                             │  │
│  │    ├── Recipe exported to InferForge DB                                     │  │
│  │    ├── Winning config saved with gain_pct                                   │  │
│  │    ├── Deploy to production via InferForge pipeline                         │  │
│  │    └── Knowledge Base updated for future sessions                           │  │
│  └─────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────┘
```

---

## Features

### 1. Conversational AI Agent — Natural Language to Production

No CLIs to memorize, no configs to edit. Just describe what you want:

| What You Say | What InferForge Does |
|-------------|---------------------|
| "Profile Llama 70B on MI300X" | Runs memory calculator → presents weight/KV/overhead breakdown + valid TP configs |
| "Benchmark vLLM on 8 GPUs" | Detects GPUs → calculates → launches Docker → parses metrics → stores results |
| "Compare TP=4 vs TP=8" | Runs benchmark at both configs → side-by-side comparison table with winner |
| "Compare vLLM vs SGLang" | Creates campaign → benchmarks both → SLA evaluation → automatic winner |
| "Optimize with Hyperloom" | Full 6-phase optimization: baseline → kernel tuning → recipe export |
| "Deploy the best config" | Promotes winning run to deployment → canary (10%) → full production |
| "What GPUs does this node have?" | SSH → amd-smi → reports GPU model, count, HBM, ROCm version |
| "Can Qwen 72B fit on 4 GPUs?" | Memory calculator → yes/no with utilization percentage |
| "Run overnight optimization" | Autonomous mode: runs everything end-to-end, results ready in morning |

### 2. Mission Control GUI (ERA Dashboard)

A real-time 4-panel dashboard with command sidebar:

```
┌──────────────────────────────────┬──────────────────────────────────┬─────────────┐
│         GPU TELEMETRY            │      OPTIMIZATION TIMELINE       │   COMMAND   │
│                                  │                                  │   SIDEBAR   │
│  ┌──────┐ ┌──────┐ ┌──────┐     │  PRELUDE     ████████░░  12min   │             │
│  │Node 1│ │Node 2│ │Node 3│     │  ENABLEMENT  █████████░   9min   │  [Config]   │
│  │8xGPU │ │8xGPU │ │8xGPU │     │  FW_AGENT    ███████████ 28min   │  Head IP    │
│  │87% ▓▓│ │42% ▓ │ │91% ▓▓│     │  KERNEL      ██████████░ 41min   │  Workers    │
│  │72°C  │ │58°C  │ │74°C  │     │  SWEEP       ███░░░░░░░ running  │  Model      │
│  │340W  │ │285W  │ │355W  │     │  CLOSE       ░░░░░░░░░░ pending  │  Framework  │
│  └──────┘ └──────┘ └──────┘     │                                  │  GPU Type   │
│                                  │  Gain: +32% throughput           │             │
├──────────────────────────────────┼──────────────────────────────────┤  [Chat]     │
│       BENCHMARK RESULTS          │      DEPLOYMENT PIPELINE         │             │
│                                  │                                  │  > Detect   │
│  Peak Throughput: 2,847 tok/s    │  ┌────────┐   ┌────────┐        │    GPUs     │
│  Median TTFT:     42.1 ms        │  │pending │──►│deploying│        │  > Memory   │
│  P99 TTFT:        89.7 ms        │  └────────┘   └────┬───┘        │    Calc     │
│  Best TP:         8              │                    │             │  > Bench-   │
│                                  │               ┌────▼───┐        │    mark     │
│  ┌─────────────────────┐         │               │ canary │        │  > Auto-    │
│  │ Throughput ▓▓▓▓▓▓▓▓ │         │               │  10%   │        │    Optimize │
│  │ Chart     ▓▓▓▓▓▓▓  │         │               └────┬───┘        │  > Deploy   │
│  │           ▓▓▓▓▓▓   │         │                    │             │    Best     │
│  └─────────────────────┘         │               ┌────▼────┐       │  > Stop All │
│                                  │               │promoted │       │             │
│                                  │               │  100%   │       │             │
│                                  │               └─────────┘       │             │
└──────────────────────────────────┴──────────────────────────────────┴─────────────┘
```

**GUI Features:**
- Live GPU utilization/temperature/power heatmap across all fleet nodes
- Optimization timeline (Gantt chart) with phase-by-phase progress
- Benchmark result charts (throughput trend, TTFT distribution)
- Deployment pipeline visualization with state transitions
- Configuration panel for cluster setup (SSH, model, framework, SLA targets)
- Quick-command buttons (Detect GPUs, Memory Calc, Benchmark, Auto-Optimize, Deploy Best)
- Chat interface with real-time agent streaming via WebSocket
- Session manager modal for browsing/comparing optimization sessions
- Auto-reconnect WebSocket with event replay

### 3. Memory & Parallelism Calculator

Deterministic, MLA-aware memory analysis engine supporting 50+ models and 8 GPU platforms:

```
$ python3 inferforge/calculator/engine.py --model "Llama-3.1-70B-Instruct" --gpu MI300X --gpu-count 8

┌──────────────────────────────────────────────────────────────────┐
│              Memory Analysis: Llama 3.1 70B Instruct             │
├──────────────────────┬───────────────────────────────────────────┤
│ Weight Memory        │  130.0 GB (bf16, 70B params)              │
│ KV Cache / Token     │  1.25 MB (GQA: 8 KV heads)               │
│ KV Cache / Request   │  160.0 MB (128K seq len)                  │
│ Overhead (10%)       │  19.2 GB per GPU                          │
│ Usable HBM           │  172.8 GB per GPU (192 GB × 0.90)        │
├──────────────────────┴───────────────────────────────────────────┤
│                    Valid Configurations                           │
├──────┬────┬────┬───────────┬──────────┬───────────┬──────────────┤
│  TP  │ PP │ DP │ Wt/GPU    │ KV Budget│ Max Batch │ Best For     │
├──────┼────┼────┼───────────┼──────────┼───────────┼──────────────┤
│   4  │  1 │  2 │  32.5 GB  │ 121.1 GB │    756    │ Throughput   │
│   8  │  1 │  1 │  16.3 GB  │ 137.3 GB │   1712    │ Max Batch    │
│   4  │  2 │  1 │  32.5 GB  │ 121.1 GB │    756    │ Multi-Node   │
└──────┴────┴────┴───────────┴──────────┴───────────┴──────────────┘
```

**Calculator Features:**
- **50+ built-in models**: Llama (2/3/3.1/3.2/3.3/4-Scout/4-Maverick), Mistral, Mixtral, Qwen (2/2.5/3), DeepSeek (V3/R1 with MLA), Phi, Gemma, Command R+, DBRX, Falcon, Yi, GPT-OSS
- **8 GPU platforms**: MI250X, MI300X, MI308X, MI325X, MI350X, MI355X, MI450X, MI455X
- **MLA-aware KV cache**: DeepSeek-style multi-head latent attention with KV LoRA rank compression
- **MoE support**: Expert memory distribution across GPUs (Expert Parallelism)
- **Attention types**: MHA (multi-head), GQA (grouped query), MLA (multi-head latent)
- **Dtype support**: bf16, fp16, fp8, int8, fp4, int4
- **Custom models**: Pass architecture params directly (no registry entry needed)

### 4. GPU Fleet Management

Register, monitor, and manage GPU nodes across your cluster:

```
┌───────────────────────────────────────────────────────────────┐
│                     Fleet Node Inventory                      │
├────────────────┬──────────┬──────┬──────────┬────────┬────────┤
│ Hostname       │ Platform │ GPUs │ HBM/GPU  │ ROCm   │ Status │
├────────────────┼──────────┼──────┼──────────┼────────┼────────┤
│ gpu-node-01    │ MI300X   │   8  │ 192 GB   │ 6.4.0  │ ● online  │
│ gpu-node-02    │ MI300X   │   8  │ 192 GB   │ 6.4.0  │ ● online  │
│ gpu-node-03    │ MI325X   │   8  │ 256 GB   │ 6.4.0  │ ● online  │
│ gpu-node-04    │ MI300X   │   8  │ 192 GB   │ 6.4.0  │ ◉ reserved│
└────────────────┴──────────┴──────┴──────────┴────────┴────────┘
```

**Fleet Features:**
- **Node registration** with GPU specs auto-detection via SSH
- **Live telemetry** polling (utilization %, temperature °C, power W per GPU)
- **Preflight health checks** — RAM, GPU count, platform verification, stale container detection
- **GPU reservation system** — reserve GPU ranges for campaigns with optional expiry
- **Node recovery** — aggressive cleanup: kill containers, free GPU memory, remove locks
- **Best-node recommendation** — ranks nodes by available RAM and GPU count
- **Multi-format amd-smi parsing** — handles modern JSON, legacy text, and rocm-smi fallback

### 5. Campaign System — Multi-Config Comparison

Compare frameworks, topologies, dtypes, and GPU platforms with SLA-based winner selection:

```
Campaign: "Llama 70B Production Config Selection"
┌───────────┬──────────┬─────┬──────────────┬────────────┬──────────┬────────┬──────────┐
│ Framework │ Topology │ DType│ Throughput   │ TTFT p50   │ TTFT p99 │ TPOT   │ Winner?  │
├───────────┼──────────┼─────┼──────────────┼────────────┼──────────┼────────┼──────────┤
│ vLLM      │ TP=8     │ bf16│ 2,847 tok/s  │ 42.1 ms    │ 89.7 ms  │ 8.2 ms │ ✅ BEST  │
│ vLLM      │ TP=4     │ bf16│ 2,103 tok/s  │ 58.3 ms    │ 142.1 ms │ 11.4 ms│          │
│ SGLang    │ TP=8     │ bf16│ 2,614 tok/s  │ 38.9 ms    │ 95.2 ms  │ 9.1 ms │          │
│ vLLM      │ TP=8     │ fp8 │ 3,291 tok/s  │ 35.7 ms    │ 78.4 ms  │ 6.8 ms │ ✅ PERF  │
└───────────┴──────────┴─────┴──────────────┴────────────┴──────────┴────────┴──────────┘
SLA: TTFT p99 < 100ms ✅ | Throughput > 2000 tok/s ✅ | TPOT p99 < 15ms ✅
Winner: vLLM TP=8 fp8 (highest throughput meeting all SLA targets)
```

### 6. Deployment Pipeline — From Benchmark to Production

A complete state machine for promoting optimized configurations:

```
                    ┌─────────┐
                    │ pending │ ── deployment created from benchmark or recipe
                    └────┬────┘
                         │
                    ┌────▼────┐
                    │building │ ── preparing container configuration
                    └────┬────┘
                         │
                    ┌────▼─────┐
                    │deploying │ ── rolling out to target node
                    └────┬─────┘
                         │
                    ┌────▼────┐
                    │ canary  │ ── running with partial traffic (10%, 25%, 50%)
                    │  10%    │
                    └──┬───┬──┘
                       │   │
              promote  │   │  rollback
                       │   │
                  ┌────▼┐ ┌▼────────┐
                  │prom-│ │rolled   │
                  │oted │ │back     │
                  │100% │ │         │
                  └─────┘ └─────────┘
```

### 7. Recipe System — Reusable Optimization Configs

Save, browse, and apply proven optimization recipes from Hyperloom sessions:

| Model | GPU | Framework | Baseline | Optimized | Gain | Key Optimizations |
|-------|-----|-----------|----------|-----------|------|-------------------|
| Llama 3.1 70B | MI300X | vLLM | 2,130 tok/s | 2,847 tok/s | +33.7% | chunked-prefill, max-num-seqs=128, Triton flash-attn v3 |
| DeepSeek R1 | MI300X | vLLM | 1,580 tok/s | 2,194 tok/s | +38.9% | MLA kernel patch, ep=8, hipBLASLt tune |
| Qwen 2.5 72B | MI325X | SGLang | 2,890 tok/s | 3,412 tok/s | +18.1% | block-size=32, RadixAttention, torch.compile |

### 8. Structured Metrics Database

Every benchmark result is stored with 40+ fields in a structured schema — no more regex parsing of log files:

| Field Category | Fields Tracked |
|---------------|---------------|
| **Model** | name, HF ID, params_b, architecture |
| **Hardware** | GPU platform, count, HBM used |
| **Topology** | TP, PP, DP, EP, dtype, KV dtype |
| **Latency** | TTFT (p50/p90/p99/mean), TPOT, ITL, E2E |
| **Throughput** | tokens/sec aggregate |
| **Config** | raw benchmark output, framework version |
| **Links** | conversation_id, campaign_id, session_id |

---

## Quick Start

### Prerequisites

| Requirement | How to Check |
|-------------|-------------|
| **Python 3.10+** | `python3 --version` |
| **SSH key access** to GPU cluster | `ssh <headnode> hostname` |
| **Anthropic API key** (or AMD LLM Gateway) | Set in `.env` or `~/.claude/settings.json` |

### Step 1: Clone

```bash
git clone https://github.com/phoenix-amd/inferforge.git
cd inferforge
```

### Step 2: Configure

```bash
cp .env.example .env
# Edit .env with your API key and cluster settings
```

### Step 3: Launch

```bash
bash start.sh
# Open http://localhost:7801
```

### Step 4: Talk to the Agent

Open the ERA dashboard and use the chat sidebar, or use any of the quick-command buttons:

| Button | What It Does |
|--------|-------------|
| **Detect GPUs** | SSH to configured node, run amd-smi, report hardware |
| **Memory Calc** | Run engine.py for configured model, show parallelism table |
| **Benchmark** | Launch Docker benchmark (vLLM/SGLang/TGI), parse metrics |
| **Auto-Optimize** | Full Hyperloom session: baseline → kernel opt → recipe |
| **GPU Status** | Live telemetry across all fleet nodes |
| **Deploy Best** | Promote winning config to canary deployment |
| **Stop All** | Kill all running containers and processes |

### Execution Modes

| Mode | Best For | Behavior |
|------|----------|----------|
| **Interactive** | First-time use, demos | Confirms before each SSH/Docker operation |
| **Autonomous** | Routine optimization | Runs end-to-end, stops only for model weight confirmation |
| **Batch** | Repeat benchmarks, CI/CD | Minimal output, fastest execution |

### Run Types

| Type | What It Does | Needs GPUs? |
|------|-------------|:-----------:|
| **Simulation** | Memory analysis + parallelism table (instant) | No |
| **Real Run** | Docker benchmark with actual vLLM/SGLang/TGI | Yes |
| **Optimize** | Full Hyperloom session (baseline + kernel optimization) | Yes |

---

## API Reference

### Core APIs (50+ Endpoints)

| Category | Endpoints | Description |
|----------|-----------|-------------|
| **Auth** | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me` | JWT authentication with bcrypt password hashing |
| **Conversations** | `GET/POST /api/conversations`, `GET/PATCH/DELETE /api/conversations/{id}` | Agent chat session management |
| **Calculator** | `POST /api/calculate`, `GET /api/models`, `GET /api/gpus` | Memory profiler with 50+ models and 8 GPUs |
| **Benchmarks** | `GET/POST /api/benchmark-runs`, `GET /api/benchmark-runs/{id}` | 40+ field benchmark result storage |
| **Campaigns** | `GET/POST /api/campaigns`, `PATCH /api/campaigns/{id}`, `POST .../launch`, `GET .../comparison` | Multi-config comparison with SLA targets |
| **Fleet** | `GET/POST /api/fleet/nodes`, `POST .../probe`, `POST /api/fleet/reserve`, `GET .../telemetry`, `POST .../preflight`, `POST .../recover` | GPU node inventory, telemetry, reservations |
| **Hyperloom** | `GET/POST /api/hyperloom/sessions`, `PATCH/DELETE .../{id}`, `POST .../launch`, `POST .../import`, `POST .../probe-phase`, `GET .../timeline`, `GET .../optimizations` | Full session lifecycle management |
| **Recipes** | `GET /api/recipes`, `GET /api/recipes/{id}`, `POST /api/recipes/sync` | Optimization recipe browsing and KB sync |
| **Deployments** | `GET/POST /api/deployments`, `PATCH .../{id}`, `POST .../promote`, `POST .../rollback` | Production deployment state machine |
| **Skills** | `GET /api/skills`, `GET /api/skills/{name}` | Agent skill discovery and metadata |
| **Health** | `GET /api/health` | Server status, API connectivity, version |

### WebSocket Endpoints

| Endpoint | Description |
|----------|-------------|
| `ws://host:7801/ws/chat/{conversation_id}` | Real-time agent chat with tool execution streaming |
| `ws://host:7801/ws/hyperloom/{session_id}` | Live Hyperloom session monitoring |
| `ws://host:7801/ws/fleet` | Fleet telemetry stream |

---

## Database Schema

12 tables with 20+ indexes for production-grade data management:

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│    users     │────►│  conversations   │────►│    messages      │
│  (accounts)  │     │  (chat sessions) │     │  (chat history)  │
└──────┬───────┘     └────────┬─────────┘     └──────────────────┘
       │                      │
       │              ┌───────┴────────────────────────┐
       │              │                                │
       ▼              ▼                                ▼
┌──────────────┐  ┌──────────────────┐  ┌──────────────────────┐
│   projects   │  │  benchmark_runs  │  │  hyperloom_sessions  │
│ (workspaces) │  │  (40+ fields)    │  │  (optimization jobs) │
└──────────────┘  └────────┬─────────┘  └──────────────────────┘
                           │
                   ┌───────┴───────┐
                   │               │
                   ▼               ▼
          ┌──────────────┐  ┌─────────────┐
          │  campaigns   │  │ deployments │
          │  (comparison)│  │ (prod serve)│
          └──────────────┘  └─────────────┘

┌──────────────┐  ┌────────────────────┐  ┌──────────────┐
│ fleet_nodes  │  │ fleet_reservations │  │   recipes    │
│ (GPU nodes)  │  │ (GPU reservations) │  │ (opt configs)│
└──────────────┘  └────────────────────┘  └──────────────┘
```

---

## Supported Models (50+)

| Family | Models | Attention | MoE |
|--------|--------|:---------:|:---:|
| **Llama** | 2-7B, 2-13B, 2-70B, 3-8B, 3-70B, 3.1-8B, 3.1-70B, 3.1-405B, 3.2-1B, 3.2-3B, 3.3-70B, 4-Scout, 4-Maverick | GQA | — |
| **Qwen** | 2-7B, 2-72B, 2.5-7B, 2.5-14B, 2.5-32B, 2.5-72B, 3-235B | GQA | — |
| **DeepSeek** | V3-671B, R1-671B | **MLA** | ✅ |
| **Mistral** | 7B-v0.3 | GQA | — |
| **Mixtral** | 8x7B, 8x22B | GQA | ✅ |
| **Phi** | 3-mini, 3-medium, 4-mini | GQA | — |
| **Gemma** | 2-9B, 2-27B | GQA/MHA | — |
| **Command R+** | 104B | GQA | — |
| **DBRX** | 132B | GQA | ✅ |
| **Falcon** | 40B, 180B | MHA/GQA | — |
| **Yi** | 34B | GQA | — |
| **GPT-OSS** | 120B | GQA | — |

## Supported GPU Platforms

| GPU | HBM | BF16 TFLOPS | FP8 TFLOPS | Memory BW | Interconnect |
|-----|-----|-------------|------------|-----------|-------------|
| MI250X | 128 GB | 383 | — | 3.28 TB/s | xGMI 400 GB/s |
| MI300X | 192 GB | 1,307 | 2,614 | 5.30 TB/s | xGMI 896 GB/s |
| MI308X | 256 GB | 1,307 | 2,614 | 5.30 TB/s | xGMI 896 GB/s |
| MI325X | 256 GB | 1,307 | 2,614 | 6.00 TB/s | xGMI 896 GB/s |
| MI350X | 288 GB | 2,300 | 4,600 | 8.00 TB/s | xGMI 1,200 GB/s |
| MI355X | 288 GB | 2,300 | 4,600 | 8.00 TB/s | xGMI 1,200 GB/s |
| MI450X | 512 GB | 4,600 | 9,200 | 12.80 TB/s | UALink 1,600 GB/s |
| MI455X | 512 GB | 4,600 | 9,200 | 12.80 TB/s | UALink 1,600 GB/s |

---

## Value Proposition for AMD

### For Field Engineers
- **Zero-to-benchmark in minutes** — no manual Docker commands, no config files, no spreadsheet math
- **One tool for everything** — profiling, benchmarking, optimization, deployment
- **Fleet visibility** — see all GPU nodes, their health, and utilization in one dashboard
- **Reproducible results** — every benchmark stored with 40+ fields, every recipe versioned

### For Product Teams
- **Competitive benchmarking** — campaign system compares vLLM vs SGLang with SLA evaluation
- **Performance claims backed by data** — structured metrics database, not screenshots of terminals
- **Recipe library** — proven optimization configs ready to deploy on customer clusters

### For Management
- **Reduce time-to-value** — customers see optimized inference performance faster
- **Lower support costs** — self-service optimization replaces manual tuning engagements
- **Showcase AMD AI platform** — conversational AI + GPU optimization = compelling demo
- **Bridge internal tools** — unifies Hyperloom's optimization engine with field-ready UX

### For Customers
- **Production-ready deployment** — canary rollout with rollback, not just benchmark numbers
- **SLA compliance** — campaigns enforce latency and throughput targets before deployment
- **Fleet management** — track all GPU nodes, reserve resources, monitor health
- **Knowledge accumulation** — recipes get better over time, benefiting all users

---

## Project Structure

```
inferforge/
├── start.sh                    # Production launcher
├── CLAUDE.md                   # Agent task specification (8,500+ lines)
├── .env                        # Configuration
│
├── inferforge/
│   ├── server.py               # FastAPI application entry point
│   ├── config.py               # Environment + settings configuration
│   │
│   ├── api/                    # 11 REST API route modules
│   │   ├── auth.py             #   JWT authentication
│   │   ├── conversations.py    #   Chat session CRUD
│   │   ├── calculator_api.py   #   Memory calculator endpoint
│   │   ├── benchmarks.py       #   Benchmark run results
│   │   ├── campaigns.py        #   Multi-config comparison
│   │   ├── fleet.py            #   GPU fleet management + telemetry
│   │   ├── hyperloom_sessions.py#  Optimization session lifecycle
│   │   ├── recipes.py          #   Optimization recipe library
│   │   ├── deployments.py      #   Production deployment pipeline
│   │   ├── skills.py           #   Agent skill discovery
│   │   ├── inference_state.py  #   Live inference state
│   │   └── websocket.py        #   WebSocket hub + streaming
│   │
│   ├── agent/                  # AI agent subsystem
│   │   ├── loop.py             #   Streaming Claude API loop
│   │   ├── system_prompt.py    #   Context-aware prompt builder
│   │   ├── tools.py            #   bash, read_file, write_file, report_metrics
│   │   └── metrics_extractor.py#   Benchmark output parser
│   │
│   ├── calculator/             # Memory & parallelism engine
│   │   ├── engine.py           #   Main calculator (CLI + API)
│   │   ├── kv_cache.py         #   KV cache formulas (MHA/GQA/MLA)
│   │   └── batch_sweep.py      #   Batch size optimization
│   │
│   ├── models/                 # Data models (8 modules)
│   │   ├── user.py, conversation.py, benchmark.py, campaign.py
│   │   ├── recipe.py, deployment.py, fleet.py, hyperloom_session.py
│   │
│   ├── db/                     # Database
│   │   └── schema.py           #   12 tables, 20+ indexes
│   │
│   ├── skills/                 # Agent skill definitions
│   │   ├── inference-optimize/ #   Coordinator skill
│   │   ├── benchmark-runner/   #   Docker execution
│   │   ├── model-profiler/     #   Memory analysis
│   │   ├── campaign-planner/   #   Comparison design
│   │   ├── fleet-manager/      #   Node operations
│   │   └── hyperloom-session/  #   Optimization management
│   │
│   └── data/                   # Reference data
│       ├── model_registry.json #   50+ model architectures
│       ├── gpu_specs.json      #   8 GPU platforms
│       └── report_format.md    #   Mandatory report template
│
├── frontend/
│   ├── era/                    # Mission Control dashboard
│   │   ├── index.html          #   4-panel + sidebar layout
│   │   ├── js/era.js           #   Dashboard logic + WebSocket
│   │   └── css/era.css         #   Dark theme styling
│   │
│   ├── nova/                   # DevOps operational view
│   └── common/                 # Shared JS/CSS modules
│       ├── api.js, state.js, chat.js, charts.js, markdown.js
│       └── css/ (variables, base, components, tables, chat)
│
└── docs/                       # Documentation
```

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.10+, FastAPI, Uvicorn |
| **Frontend** | Vanilla HTML5/JS/CSS, Chart.js, markdown-it |
| **AI Agent** | Anthropic Claude API (streaming), custom agentic loop |
| **Database** | SQLite (12 tables, JSON columns, foreign keys) |
| **Optimization** | ROCm Hyperloom (multi-agent kernel optimization) |
| **Inference** | vLLM, SGLang, TGI (Docker containers on ROCm) |
| **GPU Platform** | AMD Instinct (MI250X through MI455X), ROCm 6.x |
| **Transport** | WebSocket (real-time), REST (CRUD), SSH (fleet ops) |
| **Auth** | JWT (HS256) + bcrypt + optional HTTP Basic Auth |

---

## Relationship to Upstream Projects

InferForge is a **complementary platform** that integrates with — not replaces — existing AMD tools:

```
┌────────────────────────────────────────────────────────────────────────┐
│                          AMD AI Ecosystem                              │
│                                                                        │
│  ┌────────────────────┐                                                │
│  │     Hyperloom      │  Multi-agent kernel optimization engine        │
│  │  (AMD-AGI/Hyperloom)│  InferForge wraps this for session lifecycle, │
│  │                    │  GUI monitoring, recipe extraction             │
│  └────────┬───────────┘                                                │
│           │ integrates                                                  │
│           ▼                                                            │
│  ┌─────────────────────┐                                               │
│  │     InferForge      │  Unified platform: profiling + benchmarking   │
│  │  (this project)     │  + optimization + fleet mgmt + deployment     │
│  │                    │                                                │
│  └────────┬───────────┘                                                │
│           │ evolved from                                                │
│           ▼                                                            │
│  ┌─────────────────────────────┐                                       │
│  │   AMD Inference Agent       │  Original conversational agent for     │
│  │  (phoenix-amd/              │  GPU detection, memory profiling,      │
│  │   amd-inference-agent)      │  and Docker benchmarks                 │
│  └─────────────────────────────┘                                       │
│                                                                        │
│  Other AMD tools InferForge interfaces with:                           │
│  ├── TraceLens ── GPU trace analysis (via Hyperloom)                    │
│  ├── Magpie ──── Benchmark engine (via Hyperloom)                      │
│  ├── GEAK ────── GPU kernel generation (via Hyperloom)                  │
│  ├── amd-smi ─── GPU hardware detection (direct SSH)                   │
│  └── ROCm ────── GPU compute platform (Docker containers)              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Roadmap

| Priority | Feature | Status |
|:--------:|---------|:------:|
| P0 | Automated campaign execution engine | Planned |
| P0 | Hyperloom Experience KB sync (recipe import/export) | Planned |
| P1 | Multi-node PP benchmark orchestration | Planned |
| P1 | Fleet telemetry WebSocket (real-time push) | Planned |
| P1 | Cost tracking (LLM API + compute hours per session) | Planned |
| P2 | Job queue for sequential/parallel optimization runs | Planned |
| P2 | Grafana integration for long-term GPU monitoring | Planned |
| P2 | CI/CD integration (GitHub Actions for automated benchmarks) | Planned |

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Author

**Ryan Ghaffari** — AMD DPEG
Built to bridge the gap between profiling and production for AMD Instinct GPU inference.

---

<p align="center">
  <b>InferForge</b> — Profile. Benchmark. Optimize. Deploy.<br/>
  <i>The complete inference optimization lifecycle for AMD Instinct GPUs.</i>
</p>
