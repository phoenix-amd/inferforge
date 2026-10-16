# Memory & Parallelism Report Format

This file defines the **exact format** the agent must use when presenting
`memory_calculator.py` results. Follow every section in order. Do not skip
sections or reorder them.

---

## Section 1: Cluster Hardware Summary

Table with one row per node detected, **PLUS a mandatory Cluster Total row**.

```
| Node | Hostname | IP | GPUs | GPU Model | HBM / GPU | Total HBM | ROCm | HBM Status |
|------|----------|-----|------|-----------|-----------|-----------|------|------------|
| Head | gt-pla-u22-08.gt.cpa.ice.amd.com | 10.194.30.169 | 8 | AMD Instinct MI300X | 192 GB HBM3 | 1,536 GB | 7.2.0 | status |
| Worker | gt-pla-u20-18.gt.cpa.ice.amd.com | 10.194.30.209 | 8 | AMD Instinct MI300X | 192 GB HBM3 | 1,536 GB | 7.2.0 | status |
| **Cluster Total** | — | — | **16** | AMD Instinct MI300X | 192 GB HBM3 | **3,072 GB** | 7.2.0 | — |
```

### Mandatory rules for Section 1:
- **ALWAYS include every detected node** (head + all workers)
- **ALWAYS include the Cluster Total row** as the last row — sum GPUs and Total HBM
- **HBM Status column** shows one of:
  - `~284 MB/GPU (idle)` — OS reservation only
  - `~178 GB/GPU used (workload running)` — significant VRAM in use
- **IP column** is mandatory — show the node IP address
- **Hostname** should be the full FQDN if available (e.g. `gt-pla-u22-08.gt.cpa.ice.amd.com`)

---

## Section 2: Model Architecture

Table of model params with source note.

```
| Parameter | Value |
|-----------|-------|
| Total Parameters | 70B |
| Num Layers | 80 |
| Num Attention Heads | 64 |
| Num KV Heads | 8 (GQA -- Grouped Query Attention) |
| Hidden Size | 8,192 |
| Head Dim | 128 |
| Vocab Size | 128,256 |
| Architecture | Dense Transformer |
| Max Seq Len | 8,192 (benchmarked at 4,096) |
```

If using a registry alias, add:
> Matched to registry key `llama-3-70b` -- architecturally identical to 3.1 variant.

---

## Section 3: Memory Calculations

### 3a. Formulas Applied

**MANDATORY: All 6 rows must appear.** This is the core transparency table.

```
| Component | Formula | Calculation |
|-----------|---------|-------------|
| Weight Memory | `params x bytes_per_param` | `70x10^9 x 2 bytes = 140 GB` -> effective **130.4 GB** (accounting for embedding layers) |
| KV Cache / token | `2 x num_kv_heads x head_dim x num_layers x bytes` | `2 x 8 x 128 x 80 x 2 = 327,680 bytes` |
| KV Cache / request | `kv_per_token x seq_len` | `327,680 x 4,096 = 1.25 GB per request` |
| Activation Overhead | `10% x HBM_per_GPU` | `0.10 x 192 = 19.2 GB` (reserved for runtime, activations, fragmentation) |
| **KV Budget / GPU** | `HBM - weights - overhead` | `192 - 130.4 - 19.2 = **42.4 GB**` [TP=1 reference] |
| **Max Batch Size** | `floor(kv_budget / kv_per_req)` | `floor(42.4 / 1.25) = **33** concurrent requests` [TP=1 reference] |
```

The last two rows use the **most constrained config** (lowest TP, typically TP=1)
as the reference case. If the model doesn't fit at TP=1, use the smallest valid TP.

### 3b. Memory Breakdown Table (Single GPU / No Parallelism)

Shows how a single GPU's HBM is consumed. Uses TP=1 values.

```
| Component | Formula | Memory Required | % of 192 GB HBM |
|-----------|---------|-----------------|------------------|
| Model Weights (BF16) | 70B x 2 bytes | 130.4 GB | 67.9% |
| KV Cache (per request, seq=4096) | 2 x 8 heads x 128 dim x 80 layers x 4096 x 2B | 1.25 GB / request | 0.65% / req |
| KV Cache (batch=33, max single-GPU) | 33 x 1.25 GB | 41.3 GB | 21.5% |
| Activation Overhead | ~10% of HBM | 19.2 GB | 10.0% |
| **TOTAL** (single GPU, batch=33) | | **190.9 GB** | **99.4%** |
```

Add caution if utilization > 90%:
> CAUTION: Single-GPU utilization reaches **99.4%** at batch=33 -- extremely tight.
> Any larger batch will OOM.

---

## Section 4: HBM Utilization Visualization

Two visualization blocks using ASCII bar charts.

### 4a. Component Breakdown (1 GPU, shows what fills the HBM)

```
Weights     [############################----------------] 67.9%
KV Cache    [##########----------------------------------] 21.5%
Activations [####----------------------------------------] 10.0%
Total       [##########################################--] 99.4%  WARNING
```

### 4b. Per-TP Weight Utilization (shows how TP reduces pressure)

```
 TP=1 (single model copy):  [############################------] 67.9% -- HIGH, very limited KV cache
 TP=2 per replica:          [##############--------------------] 34.0% -- Good
 TP=4 per replica:          [#######---------------------------] 17.0% -- Excellent
 TP=8 per replica:          [####------------------------------]  8.5% -- Optimal for large batches
```

### Symbol Legend

Always include this legend below the visualization:

```
Symbol Legend:
  star   = Recommended configuration
  WARNING = HBM utilization > 90% -- risk of OOM under load
  CHECK  = HBM utilization < 50% -- comfortable headroom
  TIGHT  = Fits but < 10% free -- not production-worthy
```

---

## Section 5: Fit Analysis

Quick yes/no table for deployment scenarios.

```
| Deployment | GPUs | Total HBM | Model Fits? | Verdict |
|------------|------|-----------|-------------|---------|
| 1x MI300X | 1 | 192 GB | WARNING YES -- barely | Fits but only 33 concurrent reqs; ~3 tok/s |
| 1 Node (8x MI300X) | 8 | 1,536 GB | CHECK YES -- comfortably | Recommended. Multiple TP/DP configs. |
| 2-Node (16x MI300X) | 16 | 3,072 GB | CHECK YES -- room to spare | Multi-replica for max throughput / HA |
```

---

## Section 6: Parallelism Configuration Analysis

**MANDATORY: Include "Best For" column.** Show all valid configs ranked.

```
| Config | TP | PP | DP | Weight/GPU | KV Budget/GPU | HBM Util | Max Batch | Est. Throughput | Best For |
|--------|----|----|-----|------------|---------------|----------|-----------|-----------------|----------|
| TP=8, PP=1 star | 8 | 1 | 1 | 16.3 GB | 156.5 GB | 8.5% | 1,001 reqs | ~106 tok/s | Lowest latency -- all 8 GPUs per request |
| TP=4, PP=1 | 4 | 1 | 2 | 32.6 GB | 140.2 GB | 17.0% | 448 reqs | ~106 tok/s | **Max throughput** -- 2 replicas, high concurrency |
| TP=2, PP=1 | 2 | 1 | 4 | 65.2 GB | 107.6 GB | 34.0% | 172 reqs | ~106 tok/s | **Best throughput/GPU efficiency** -- 4 replicas |
| ... | | | | | | | | | |
| TP=1, PP=1 | 1 | 1 | 8 | 130.4 GB | 42.4 GB | 67.9% | 33 reqs | ~27 tok/s | *Avoid* -- weights use 68% HBM each |
```

### Column Definitions

| Column | Meaning |
|--------|---------|
| Config | TP/PP label. Star marks the recommended config. |
| TP | Tensor Parallelism -- GPUs splitting model weights |
| PP | Pipeline Parallelism -- GPUs splitting layers sequentially |
| DP | Data Parallelism -- independent model replicas |
| Weight/GPU | Model weight memory per GPU after TP+PP sharding |
| KV Budget/GPU | Remaining HBM available for KV cache per GPU |
| HBM Util | Weight memory as % of per-GPU HBM (lower = more KV room) |
| Max Batch | Maximum concurrent requests before KV cache OOM |
| Est. Throughput | Estimated output tokens/second (memory-bandwidth-bound) |
| Best For | Use-case recommendation for this config |

### Best For Labels (standard set)

| TP | PP | DP | Best For Label |
|----|----|----|----------------|
| =gpu_count | 1 | 1 | Lowest latency -- all N GPUs per request |
| gpu_count/2 | 1 | 2 | **Max throughput** -- 2 replicas, high concurrency |
| 2 | 1 | gpu_count/2 | **Best throughput/GPU efficiency** -- N replicas |
| any | 2 | any | Large batch + pipeline |
| any | any | any (balanced) | Balanced |
| any | 4+ | any | Low memory per GPU |
| 1 | 8 | 1 | *Avoid* -- PP adds bubble overhead |
| 1 | 4 | 2 | *Avoid* -- suboptimal |
| 1 | 2 | 4 | *Avoid* |
| 1 | 1 | gpu_count | *Avoid* -- weights use N% HBM each |

---

## Section 6b: Batching Optimization (on recommended config)

**MANDATORY for both Simulation and Real Run.** Shows how batching parameters
affect KV cache usage, throughput, and latency on the recommended TP config.

### Simulation: Estimated Impact Table

Uses `batch_sweep` output from `memory_calculator.py --json`.

```
| max-num-seqs | Chunked Prefill | KV Used/GPU | KV Util % | HBM Util % | Est. Throughput | TTFT Impact | Decode Impact | Recommendation |
|:------------:|:---------------:|:-----------:|:---------:|:----------:|:---------------:|:-----------:|:-------------:|:--------------:|
| 32 | ON  | 20.0 GB | 18.6% | 44.4% | ~26 tok/s | lower p99 (varies) | small overhead (varies) | |
| 32 | OFF | 20.0 GB | 18.6% | 44.4% | ~26 tok/s | baseline | baseline | |
| 64 | ON  | 40.0 GB | 37.2% | 54.8% | ~51 tok/s | lower p99 (varies) | small overhead (varies) | Best for latency |
| 64 | OFF | 40.0 GB | 37.2% | 54.8% | ~53 tok/s | baseline | baseline | |
| 128 | ON  | 80.0 GB | 74.3% | 75.6% | ~103 tok/s | lower p99 (varies) | small overhead (varies) | Balanced |
| 128 | OFF | 80.0 GB | 74.3% | 75.6% | ~106 tok/s | baseline | baseline | Best for throughput |
```

### Real Run: Measured Comparison Table

In Real Run mode, the agent benchmarks the top 3 batch settings from the sweep
and reports **measured** metrics:

```
| max-num-seqs | Chunked Prefill | Throughput (tok/s) | TTFT p50 | TTFT p99 | TPOT p50 | ITL p50 | E2E p50 | Recommendation |
|:------------:|:---------------:|:------------------:|:--------:|:--------:|:--------:|:-------:|:-------:|:--------------:|
| 64 | ON  | measured | ms | ms | ms | ms | ms | Best for latency |
| 128 | OFF | measured | ms | ms | ms | ms | ms | Best for throughput |
| 128 | ON  | measured | ms | ms | ms | ms | ms | Balanced |
```

### What These Parameters Do

| Parameter | What It Controls | Impact |
|-----------|-----------------|--------|
| `--max-num-seqs` | Max concurrent sequences in the decode batch | Higher = more throughput, more KV cache used |
| `--enable-chunked-prefill` | Split long prefills into chunks so decodes aren't blocked | ON = lower TTFT p99 (prefills don't stall decodes), small throughput overhead (varies by workload) |
| `--disable-chunked-prefill` | Prefills run as full batch, blocking decodes | OFF = higher raw throughput, but TTFT spikes under load |
| `--num-scheduler-steps` | Multi-step scheduling (batch multiple decode steps) | Higher = less scheduling overhead, better GPU utilization |

### Chunked Prefill: Detailed Analysis

```
Without chunked prefill (--disable-chunked-prefill):
  Request arrives -> [=========PREFILL=========][D][D][D][D]...
  Other requests:    [........BLOCKED..........][D][D][D][D]...
  Problem: Long prefills (4096+ tokens) block ALL decode steps -> TTFT spikes

With chunked prefill (--enable-chunked-prefill):
  Request arrives -> [PRE][D][D][PRE][D][D][PRE][D][D][FILL DONE][D][D]...
  Other requests:    [D][D][D][D][D][D][D][D][D][D][D][D]...
  Benefit: Decodes interleave with prefill chunks -> stable TTFT, small decode overhead (varies by workload)
```

**Rule of thumb:**
- Interactive/chat workloads -> chunked prefill ON (stable latency matters)
- Batch processing -> chunked prefill OFF (maximize raw throughput)
- Mixed workloads -> chunked prefill ON with high max-num-seqs (best of both)

---

## Section 7: Recommendation

Three tiers: Latency, Throughput, Cost Efficiency.

### Format

```
### 1st: For Minimum Latency -> TP=8, PP=1, DP=1
[vllm command block]
- All 8 GPUs collaborate on every request -> lowest TTFT
- 16.3 GB weights per GPU, 156.5 GB KV budget
- HBM utilization: ~8.5% -- massive headroom

### 2nd: For Maximum Throughput -> TP=4, PP=1, DP=2
[vllm command block]
- 2 independent replicas, each using 4 GPUs
- Best requests/second throughput at high load

### 3rd: For Cost Efficiency -> TP=2, PP=1, DP=4
- Minimum TP needed, 4 replicas
- Best requests/second per GPU metric
```

---

## Section 8: Key Takeaways

Quick Q&A table summarizing the analysis.

```
| Question | Answer |
|----------|--------|
| Fits on 1 GPU? | WARNING Yes, but only 33 concurrent reqs at seq=4096 |
| Fits on 1 node (8x MI300X)? | CHECK Yes, comfortably -- 10 valid configs |
| Requires multi-node? | No -- single node is sufficient |
| Minimum TP to fit? | TP=1 (but tight -- 67.9% HBM for weights) |
| Recommended TP for prod? | TP=8 (latency) or TP=4 (throughput) |
| FP8 needed? | No -- BF16 fits easily on 2+ GPUs |
| KV cache pressure? | None at TP>=2 -- 100+ GB KV budget |
```

---

## Formatting Rules

1. **Never dump raw JSON** -- always parse and present in tables
2. **Always show formulas** -- the Formulas Applied table is mandatory
3. **Bold key numbers** -- weight memory, KV budget, max batch, utilization %
4. **Use monospace for formulas** -- wrap in backticks
5. **Consistent units** -- always "GB" not "GiB", always "tok/s" not "tokens/sec"
6. **Section headers** -- use emoji prefixes consistently:
   - Hardware: server emoji
   - Model: page emoji
   - Memory: calculator emoji
   - HBM Viz: bar chart emoji
   - Fit Analysis: checkmark emoji
   - Parallelism: gear emoji
   - Recommendation: trophy emoji
   - Takeaways: key emoji
7. **Always include the symbol legend** after any visualization
8. **All 6 formula rows** must appear in Section 3a -- never omit KV Budget or Max Batch
