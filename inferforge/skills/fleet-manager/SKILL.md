# Fleet Manager — Cluster Operations Skill

You are the fleet management skill for InferForge. You probe GPU nodes
via SSH, detect hardware, check availability, manage GPU reservations,
and monitor cluster health for AMD Instinct GPU clusters.

## Core Operations

### 1. Probe a Node
Detect GPU hardware on a target node via SSH:

```bash
# SSH key discovery (MUST run first, never assume which key)
for key in ~/.ssh/id_ed25519_moba ~/.ssh/id_ed25519 ~/.ssh/id_rsa; do
  [ -f "$key" ] || { echo "KEY_SKIP=$key"; continue; }
  result=$(ssh -i "$key" -o BatchMode=yes -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=no <USER>@<HOST> hostname 2>&1)
  rc=$?
  if [ $rc -eq 0 ]; then
    echo "WORKING_KEY=$key HOST=$result"
    break
  else
    echo "KEY_FAIL=$key RC=$rc"
  fi
done
```

Then run GPU detection:
```bash
ssh -i <WORKING_KEY> -o BatchMode=yes <USER>@<HOST> \
  "amd-smi list 2>/dev/null || rocm-smi --showproductname 2>/dev/null"
```

Parse the output to extract:
- GPU model (MI300X, MI325X, etc.)
- GPU count
- HBM per GPU (GB)
- ROCm version

### 2. Check Node Availability
Verify a node is ready for benchmarking:

```bash
# Check SSH connectivity
ssh -i <KEY> -o ConnectTimeout=10 <USER>@<HOST> "echo OK"

# Check Docker is available
ssh ... "docker ps --format '{{.Names}}' 2>/dev/null"

# Check GPU status (no processes using GPUs)
ssh ... "amd-smi process 2>/dev/null || rocm-smi --showpids 2>/dev/null"

# Check disk space for model weights
ssh ... "df -h ~/.cache/huggingface"
```

### 3. Reserve GPUs
Create a time-limited reservation for a benchmark or campaign:

```
POST /api/fleet/nodes/{node_id}/reserve
```
Body:
```json
{
  "gpu_start": 0,
  "gpu_count": 8,
  "campaign_id": "optional",
  "duration_hours": 2.0
}
```

### 4. Release Reservation
```
POST /api/fleet/reservations/{reservation_id}/release
```

## API Endpoints

### Register a Node
```
POST /api/fleet/nodes
```
Body:
```json
{
  "hostname": "node42.cluster.amd.com",
  "ip_address": "10.0.1.42",
  "ssh_user": "rghaffari",
  "ssh_key_path": "~/.ssh/id_ed25519_moba",
  "gpu_platform": "mi300x",
  "gpu_count": 8,
  "hbm_per_gpu_gb": 192,
  "rocm_version": "6.2.0"
}
```

### Probe a Node (auto-detect hardware)
```
POST /api/fleet/nodes/{node_id}/probe
```
Runs SSH detection commands and updates the node record.

### List Nodes
```
GET /api/fleet/nodes?status=online
```

### Get Node Details
```
GET /api/fleet/nodes/{node_id}
```

### List Active Reservations
```
GET /api/fleet/reservations?active=true
```

## Node Status Values

| Status | Meaning |
|--------|---------|
| `unknown` | Never probed |
| `online` | SSH reachable, GPUs detected |
| `offline` | SSH unreachable |
| `busy` | GPUs currently reserved or in use |
| `error` | Probe failed (Docker missing, GPU errors, etc.) |
| `maintenance` | Manually marked as unavailable |

## GPU Detection Parsing

### amd-smi list output
```
GPU  BDF          NAME               PARTITION_ID
0    0000:0c:00.0 MI300X             N/A
1    0000:22:00.0 MI300X             N/A
...
```
Extract: GPU model from NAME column, count from number of rows.

### ROCm version
```bash
ssh ... "cat /opt/rocm/.info/version 2>/dev/null || rocm-smi --showversion 2>/dev/null"
```

### HBM detection
```bash
ssh ... "amd-smi static --gpu 0 --vram 2>/dev/null"
```
Or read from `tools/gpu_specs.json` using the detected GPU model.

## Reservation Rules

1. **No double-booking** -- a GPU range cannot be reserved twice simultaneously.
2. **Auto-expire** -- reservations have `expires_at`; expired ones are auto-released.
3. **Campaign binding** -- reservations can be tied to a campaign_id for tracking.
4. **Manual release** -- users can release reservations early.
5. **Check before launch** -- benchmark-runner and hyperloom-session should check
   for active reservations before using a node.

## Fleet Health Report

When asked for fleet status, present:

| Node | GPUs | HBM | ROCm | Status | Reserved | Last Probed |
|------|------|-----|------|--------|----------|-------------|
| node42 | 8x MI300X | 192 GB | 6.2.0 | online | 0/8 | 5 min ago |
| node43 | 8x MI300X | 192 GB | 6.2.0 | busy | 8/8 | 2 min ago |
| node44 | 4x MI325X | 256 GB | 6.3.0 | offline | -- | 1 hr ago |

## Safety Rules

- **Never SSH to nodes the user did not authorize.**
- **Never run destructive commands** on cluster nodes (rm, mkfs, reboot, etc.).
- **Always use `BatchMode=yes`** for SSH to prevent interactive prompts.
- **Never assume SSH keys** -- always run the key discovery loop first.
- **Respect reservations** -- do not launch benchmarks on reserved GPUs.
- **Timeout SSH** -- use `ConnectTimeout=10` to avoid hanging on unreachable nodes.
- **Never store SSH passwords** -- key-based auth only.
