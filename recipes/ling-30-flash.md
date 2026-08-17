# Ant Ling 3.0 Flash (124B-A5B) on one DGX Spark — what works and what doesn't

## INT4 — the recipe that works today (benched: 86/100 hardmode, 28.2 tok/s c1)

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

## NVFP4 — fork-only territory; measure before trusting

- **Do NOT use the official `inclusionAI/Ling-3.0-flash-fp4` (MXFP4)** on GB10:
  community consensus is it falls back to software emulation (slow AND
  quality-degrading), and it needs a custom SGLang branch anyway.
- **olka-fi/Ling-3.0-flash-NVFP4**: does not load on the SGLang `ling_v3_support`
  image — `Unable to find matching target for
  model.layers.0.self_attn.fused_qkvbfg_proj in the compressed-tensors config`
  (checkpoint quantized against vLLM module naming; the fork fuses QKV
  differently). Its vLLM path needs the `inclusionAI/vllm` `ling_3_0` fork plus
  three manual patches with a documented SwiGLU-clamp correctness trap.
- **AtomicChat/Ling-3.0-flash-NVFP4**: card self-declares broken; needs an
  unmerged vLLM PR. Skip.
- **r0b0tlab/Ling-3.0-flash-NVFP4**: the credible one — validated on GB10 by its
  author (33.5 tok/s w/ MTP-1, 73.2% acceptance) with a click-run
  [reproducibility repo](https://github.com/r0b0tlab/ling-3.0-flash-nvfp4).
  Fixes we needed to actually build/run it (as of 2026-08-17):
  1. Dockerfile clones the fork then `git fetch origin <short-sha>` — GitHub
     refuses short-SHA fetches. The pinned commit IS the branch head, so verify
     `rev-parse HEAD` instead of fetch+checkout.
  2. `flashinfer==0.6.15.post1` is not on PyPI — the package is
     `flashinfer-python==0.6.15.post1`.
  3. The default base (`nvcr.io/nvidia/pytorch:25.01-py3`, CUDA 12.8 nvcc) cannot
     JIT FlashInfer's sm_121 CUTLASS MoE modules ("No supported CUDA
     architectures found for major versions [12]"). Rebuild with
     `--build-arg CUDA_IMAGE=nvcr.io/nvidia/pytorch:26.01-py3` (CUDA 13).
  4. No flashinfer cubin wheel covers sm_120/121 — the NVFP4 MoE kernels always
     JIT at first load. Run the warmup with NO weights resident (the JIT compile
     alongside an 81GB model load can OOM the host), set
     `FLASHINFER_CUDA_ARCH_LIST=12.1` and bound `MAX_JOBS`.
