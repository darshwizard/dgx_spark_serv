#!/usr/bin/env bash
# Qwen3.8-27B NVFP4 + DSpark speculative decoding on SGLang (GB10).
#
# Config, image digest and checkpoint revisions all come from
# github.com/hasso5703/dgx-spark-qwen38, validated 2026-08-15 at 34-38 tok/s
# decode (peak 46.7 on GSM8K-style work), against ~24.5 tok/s for the same model
# on vLLM 0.27 NVFP4. The gain is DSpark accepting 3.3-4.9 tokens per step, so
# expect the bottom of that range on prose (acceptance ~1.8) and the top on
# maths and code (~4.9).
#
# THREE DELIBERATE DEPARTURES from that repo's systemd unit:
#
#  1. No systemd. Installing the unit needs sudo, and a unit enabled at boot
#     would seize the GPU behind gpu.sh's back -- the one thing this box's
#     single-GPU arbitration exists to prevent. Run through `gpu.sh qwen38`
#     instead, which releases whatever holds the GPU first.
#
#  2. Binds 127.0.0.1, not 0.0.0.0. The upstream unit publishes on every
#     interface and protects the port with --api-key. That key cannot survive
#     this box's gateway: it forwards the CALLER's Authorization header verbatim
#     and has no per-backend credential, so its /v1/models liveness probe would
#     get a 401, mark the backend down, and 503 every request. Loopback plus no
#     key keeps the gateway working AND keeps the model off the LAN, which is
#     strictly tighter than the upstream default.
#
#  3. --restart on-failure:2 rather than always. SGLang allocates 25-40 GB of
#     TRANSIENT unified memory during CUDA graph capture that its own accounting
#     never sees, which is why the container is hard-capped at 100g below and why
#     upstream warns not to run it natively. An unbounded restart policy turns a
#     memory failure into a loop that re-spikes 40 GB every 15 seconds, which is
#     how this box gets wedged. Two attempts, then it stays down and visible.
set -euo pipefail

IMAGE="${IMAGE:-lmsysorg/sglang@sha256:febfb971c7352570fc445c466ebd6ffc9d896024958e544a60f2137fd85856b1}"
NAME="qwen38-sglang"
PORT="${PORT:-30000}"
HF_CACHE="${HF_CACHE:-$HOME/.cache/huggingface}"
CONFIG_DIR="$HOME/.config/qwen38"

# Replace any existing container. Refuses while requests are in flight unless
# FORCE=1, matching the other launchers -- a restart drops them mid-generation.
if docker ps -a --format '{{.Names}}' | grep -qx "${NAME}"; then
  if docker ps --format '{{.Names}}' | grep -qx "${NAME}"; then
    # `|| true` because a SIGPIPE from the early-closing `head` is exit 23, which
    # pipefail would otherwise turn into a fatal error. Absent metric -> 0.
    running=$(curl -s --max-time 5 "http://localhost:${PORT}/metrics" 2>/dev/null \
              | awk '/^sglang:num_running_reqs/ {print int($2)}' | head -1 || true)
    running="${running:-0}"
    if [ "${running}" -gt 0 ] && [ "${FORCE:-0}" != "1" ]; then
      echo "REFUSING: ${running} request(s) in flight on :${PORT}." >&2
      echo "Wait for them to drain, or re-run with FORCE=1 to kill them." >&2
      exit 1
    fi
  fi
  echo "Removing existing '${NAME}'..."
  docker rm -f "${NAME}" >/dev/null
fi

# Same reason as the vLLM launchers: starting into a half-released CUDA context
# fails during kernel load. Wait for the driver to finish reclaiming it.
if [ -n "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)" ]; then
  echo -n "Waiting for GPU to settle"
  for _ in $(seq 1 30); do
    [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)" ] && break
    echo -n "."; sleep 2
  done
  sleep 3; echo " ok"
fi

[ -s "${CONFIG_DIR}/chat-template-sglang.jinja" ] || {
  echo "Missing ${CONFIG_DIR}/chat-template-sglang.jinja." >&2
  echo "Generate it: python3 ~/dgx-spark-qwen38/patch-template.py \"${HF_CACHE}\" \"${CONFIG_DIR}/chat-template-sglang.jinja\"" >&2
  exit 1; }

mkdir -p "${CONFIG_DIR}/sglang-cache"

# --mem-fraction-static 0.50 is upstream's figure and upstream is explicit that
# raising it freezes the machine: the static pool is only the part SGLang counts,
# and graph capture adds the untracked 25-40 GB on top. --memory 100g is the
# backstop that turns "wedge the box" into "the container dies".
docker run -d \
  --name "${NAME}" \
  --restart on-failure:2 \
  --gpus all \
  --memory 100g --memory-swap 100g --shm-size 16g \
  --network host --ipc=host \
  -e TORCHINDUCTOR_CACHE_DIR=/cache/inductor \
  -v "${CONFIG_DIR}/sglang-cache":/cache \
  -v "${HF_CACHE}":/root/.cache/huggingface \
  -v "${CONFIG_DIR}":/out \
  "${IMAGE}" \
  python3 -m sglang.launch_server \
    --trust-remote-code --model-path RadixArk/Qwen3.8-27B-NVFP4 --tp-size 1 \
    --served-model-name qwen3.8-27b \
    --mem-fraction-static 0.50 \
    --attention-backend flashinfer --chunked-prefill-size 8192 \
    --disable-prefill-cuda-graph --cuda-graph-max-bs 4 \
    --speculative-algorithm DSPARK \
    --speculative-draft-model-path RadixArk/Qwen3.8-27B-DSpark \
    --speculative-dspark-block-size 7 --speculative-draft-model-quantization unquant \
    --mamba-scheduler-strategy extra_buffer \
    --enable-torch-compile --torch-compile-max-bs 4 \
    --num-continuous-decode-steps 2 \
    --reasoning-parser qwen3 --tool-call-parser qwen3_coder \
    --chat-template /out/chat-template-sglang.jinja \
    --enable-metrics \
    --host 127.0.0.1 --port "${PORT}"

echo "Started '${NAME}' on 127.0.0.1:${PORT} (loopback only; reach it through the gateway on :8080)."
echo "First boot is ~9 minutes: torch.compile plus CUDA graph capture. Follow: docker logs -f ${NAME}"
