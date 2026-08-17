# Ant Ling 3.0 Flash (124B-A5B) on one DGX Spark

## INT4 — the working recipe (benched: 86/100 hardmode, 28.2 tok/s c1)

Use [MiaAI-Lab/Ling-3.0-Flash-SGLang-DGX-Spark](https://github.com/MiaAI-Lab/Ling-3.0-Flash-SGLang-DGX-Spark)
(prebuilt SGLang image with the `ling_v3_support` branch baked in;
`inclusionAI/Ling-3.0-flash-int4`, 72GB). Our invocation — the conservative
unified-memory profile their own docs recommend:

```bash
DOCKER_MEMORY=110g MEM_FRACTION_STATIC=0.70 MAX_MAMBA_CACHE_SIZE=16 ./start.sh
```

Serves on :8888 with NEXTN speculative decoding, fp8 KV, 256k context.
Note: the server reports the model under its snapshot PATH, not a friendly name —
query `/v1/models` for the exact id before benching.

Measured (tool-eval-bench hardmode seed 42 + llama-benchy): quality 86/100,
median turn 4.3s, decode 28.2 tok/s c1 (21.0 at 8k depth), prefill 2,365–2,726
tok/s, c2 aggregate 43.5. Weakest category: autonomous planning (33%).

## Other quantizations

As of 2026-08-17, INT4 is the only Ling 3.0 Flash quantization we could serve
on this hardware. The FP4/NVFP4 checkpoints (official and community) all failed
— they require forked, patched serving stacks that did not run on a stock GB10
setup. If you want 4-bit-float Ling on a Spark, wait for upstream vLLM/SGLang
support rather than fighting the forks.
