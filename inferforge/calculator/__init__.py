"""InferForge Calculator -- memory analysis and parallelism configuration engine."""

from inferforge.calculator.engine import (
    calc_weight_memory_gb,
    generate_configs,
    recommend,
    load_json,
    BYTES_PER_PARAM,
    OVERHEAD_FRACTION,
)
from inferforge.calculator.kv_cache import (
    calc_kv_cache_per_token_bytes,
    calc_kv_cache_per_request_gb,
    describe_attention_type,
)
from inferforge.calculator.batch_sweep import generate_batch_sweep

__all__ = [
    "calc_weight_memory_gb",
    "calc_kv_cache_per_token_bytes",
    "calc_kv_cache_per_request_gb",
    "describe_attention_type",
    "generate_configs",
    "generate_batch_sweep",
    "recommend",
    "load_json",
    "BYTES_PER_PARAM",
    "OVERHEAD_FRACTION",
]
