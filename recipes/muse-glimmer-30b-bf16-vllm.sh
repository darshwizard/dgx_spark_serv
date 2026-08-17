#!/usr/bin/env bash
# meta-models/Muse-Glimmer-30B in BF16 on a DGX Spark (GB10) — via the model's
# dedicated vLLM image (native arm64).
#
# READ THIS FIRST: dense 30B in BF16 decodes at ~4.3 tok/s on GB10. That is not
# a config problem — it is memory bandwidth (~60GB of weights per token over a
# ~270GB/s unified bus ≈ 4.5 tok/s ceiling). Measured: hardmode quality 81/100,
# 44s median agent turn. Fine for batch/offline; unusable interactively.
# The NVFP4 variant (25GB) is the deployment-grade fit for this hardware.
set -euo pipefail

NAME="${NAME:-muse-glimmer}"
PORT="${PORT:-8010}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"

until [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)" ]; do sleep 2; done; sleep 5

docker run -d --name "${NAME}" --network host --gpus all --shm-size 16g \
  --memory 110g --memory-swap 110g --restart no \
  -v "${HF_CACHE}:/root/.cache/huggingface" \
  vllm/vllm-openai:muse-glimmer \
  meta-models/Muse-Glimmer-30B \
  --served-model-name muse-glimmer \
  --host 0.0.0.0 --port "${PORT}" \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.65 --max-model-len 131072 \
  --enable-auto-tool-choice --tool-call-parser muse_glimmer \
  --reasoning-parser muse_glimmer \
  --generation-config auto

echo "Started '${NAME}' on :${PORT}. ~55GiB of BF16 weights; boot ~9 min."
