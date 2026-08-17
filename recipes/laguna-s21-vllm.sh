#!/usr/bin/env bash
# poolside/Laguna-S-2.1-NVFP4 (117.6B-A8.5B MoE) on ONE DGX Spark (GB10, sm_121a).
#
# Two configs benched head-to-head on the same weights + image (see RESULTS.md):
#
#   CONFIG=dflash  (default) — DFlash drafter + b12x backends:
#                  hardmode 81/100, 18.2 tok/s c1 decode, 3.2s median agent turn
#   CONFIG=plain   — Weschera-style validated config (no drafter, no b12x flags):
#                  hardmode 83/100, 17.5 tok/s c1 decode, 2,450 tok/s prefill
#
# Verdict: near-equivalent. DFlash buys ~4% decode and faster agent turns;
# b12x flags cost prefill. Pick per workload.
#
# HARD-LEARNED CONSTRAINTS (this exact snapshot, 93G on disk):
#  * vLLM >= 0.25 is MANDATORY. Older stacks chat fine but emit token salad the
#    moment tools are attached (silent!). Always run the tool probe below.
#  * 256k context does NOT fit at util 0.85 on 121GB unified (needs 9.3GiB KV,
#    ~4.5 free). 64k boots; ~122k is the estimated ceiling. The card's 1M claim
#    is not reachable on one Spark with this quant.
#  * util 0.8 + 131k (the recipe as published) under-fits on heavier images:
#    KV computed NEGATIVE on our vLLM 0.26.1 build. Size against YOUR image.
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/miaai-lab/mia-vllm-gb10-linear-b12x:latest}"   # vLLM 0.26.1, aarch64, nvcc 13.2
NAME="${NAME:-laguna-s21}"
PORT="${PORT:-8003}"
CONFIG="${CONFIG:-dflash}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"

EXTRA=()
if [ "${CONFIG}" = "dflash" ]; then
  EXTRA+=(--moe-backend auto --linear-backend flashinfer_b12x
          --attention-backend flashinfer
          --speculative-config '{"model":"poolside/Laguna-S-2.1-DFlash-NVFP4","num_speculative_tokens":7,"method":"dflash"}'
          --enable-prefix-caching --max-num-seqs 4)
else
  EXTRA+=(--max-num-seqs 32)   # poolside: mandatory in their reference config
fi

# One tenant per GPU: never launch into a half-released CUDA context.
until [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)" ]; do sleep 2; done; sleep 5

docker run -d --gpus all \
  --name "${NAME}" \
  --network host --ipc host --shm-size 8g \
  --memory 110g --memory-swap 110g --restart no \
  -e HF_HUB_OFFLINE=1 -e VLLM_TRUST_REMOTE_CODE=1 -e CUTE_DSL_ARCH=sm_121a \
  -v "${HF_CACHE}:/root/.cache/huggingface" \
  "${IMAGE}" \
  vllm serve poolside/Laguna-S-2.1-NVFP4 \
    --served-model-name laguna-s \
    --host 0.0.0.0 --port "${PORT}" \
    --tensor-parallel-size 1 --trust-remote-code \
    --kv-cache-dtype fp8 \
    --gpu-memory-utilization 0.85 --max-model-len 65536 \
    --reasoning-parser poolside_v1 --tool-call-parser poolside_v1 --enable-auto-tool-choice \
    --override-generation-config '{"temperature":0.7,"top_p":0.95}' \
    "${EXTRA[@]}"

cat <<EOF
Started '${NAME}' on :${PORT} (config: ${CONFIG}). Boot ~10-16 min.
DO NOT SKIP the tool probe once healthy — it catches the old-vLLM token-salad bug:
  curl -s http://localhost:${PORT}/v1/chat/completions -H 'Content-Type: application/json' -d '{
    "model":"laguna-s","temperature":0,"max_tokens":200,
    "messages":[{"role":"user","content":"What is the weather in Houston? Use the tool."}],
    "tools":[{"type":"function","function":{"name":"get_weather","description":"Get weather",
      "parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}]}'
GOOD: message.tool_calls populated.  BAD: null tool_calls + gibberish content.
EOF
