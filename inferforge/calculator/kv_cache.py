"""Architecture-aware KV cache calculation for LLM inference.

Supports MHA, GQA, MQA, and MLA (DeepSeek Multi-head Latent Attention)
attention types with per-dtype byte sizing.
"""

BYTES_PER_ELEMENT = {
    "bf16": 2,
    "fp16": 2,
    "fp8": 1,
    "int8": 1,
    "fp4": 0.5,
    "int4": 0.5,
}


def calc_kv_cache_per_token_bytes(
    num_layers: int,
    num_kv_heads: int,
    head_dim: int,
    kv_dtype: str = "bf16",
    attention_type: str = "gqa",
    mla_config: dict | None = None,
) -> int:
    """KV cache bytes per token across all layers.

    Args:
        num_layers:     Number of transformer layers.
        num_kv_heads:   Number of KV heads (ignored for MLA).
        head_dim:       Dimension per attention head (ignored for MLA).
        kv_dtype:       Data type for KV cache storage.
        attention_type: One of "mha", "gqa", "mqa", "mla".
        mla_config:     Required when attention_type == "mla".
                        Keys: "kv_lora_rank" (int), "qk_rope_head_dim" (int).

    Returns:
        Integer byte count per token (K + V combined, all layers).
    """
    bpe = BYTES_PER_ELEMENT.get(kv_dtype, 2)

    if attention_type == "mla":
        if mla_config is None:
            raise ValueError(
                "mla_config with 'kv_lora_rank' and 'qk_rope_head_dim' "
                "is required for MLA attention"
            )
        kv_lora_rank = mla_config["kv_lora_rank"]
        qk_rope_head_dim = mla_config["qk_rope_head_dim"]
        # MLA stores compressed KV: 2 * (kv_lora_rank + qk_rope_head_dim) per layer
        return int(2 * (kv_lora_rank + qk_rope_head_dim) * num_layers * bpe)

    # Standard attention: MHA / GQA / MQA
    # MHA: kv_heads == num_heads (caller passes the full head count)
    # GQA: kv_heads < num_heads
    # MQA: kv_heads == 1
    # Formula: 2 (K+V) * kv_heads * head_dim * layers * bytes_per_element
    return int(2 * num_kv_heads * head_dim * num_layers * bpe)


def calc_kv_cache_per_request_gb(kv_per_token_bytes: int, seq_len: int) -> float:
    """KV cache for one full-length request in GB."""
    return kv_per_token_bytes * seq_len / (1024 ** 3)


def describe_attention_type(attention_type: str, num_heads: int, num_kv_heads: int) -> str:
    """Human-readable label for the attention mechanism."""
    labels = {
        "mha": f"MHA (Multi-Head Attention) -- {num_heads} heads",
        "gqa": f"GQA (Grouped Query Attention) -- {num_heads} attn, {num_kv_heads} KV",
        "mqa": f"MQA (Multi-Query Attention) -- {num_heads} attn, 1 KV",
        "mla": f"MLA (Multi-head Latent Attention) -- compressed KV",
    }
    return labels.get(attention_type, f"Unknown ({attention_type})")
