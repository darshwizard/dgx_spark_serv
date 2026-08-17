#!/usr/bin/env bash
# Qwen3.6-35B-A3B (general reasoning MoE) NVFP4 on vLLM — MiaAI-Lab's recommended GB10
# config. Custom image with the FlashInfer B12X linear kernel (native sm_121 NVFP4) +
# MTP speculative decoding (2 tokens). Reported ~95 tok/s decode / 103ms TTFT at c1.
# This is the vLLM replacement for the retired Lemonade/GGUF 35B.
set -euo pipefail

IMAGE="ghcr.io/miaai-lab/mia-vllm-gb10-linear-b12x:latest"
NAME="qwen35-nvfp4"
PORT="8004"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# MEMORY BUDGET -- sized 2026-08-12 for 4 conversations at the full 262,144
# context, from numbers measured on the running engine rather than estimated:
#
#   KV for 4 x 262,144 = 1,048,576 tokens @ 12,436.7 B/token    12.15 GiB
#   non-KV at idle (weights + CUDA graphs + workspaces)         29.59 GiB
#   -------------------------------------------------------------------
#   idle footprint, measured                                    41.74 GiB
#   activation growth under a 216k-token prefill                 6.88 GiB
#   -------------------------------------------------------------------
#   observed peak at 216k context                               48.62 GiB
#   projected peak at the full 262k max-model-len              ~50    GiB
#
# Bytes/token comes from the engine's own report of 1,572,864 tokens for
# 19,561,292,085 bytes. The idle figure is nvidia-smi minus the KV pool.
#
# --gpu-memory-utilization 0.45 = 54.76 GiB, i.e. ~5 GiB over the projected peak.
#
# It was briefly 0.40 (48.68 GiB), sized against the IDLE footprint alone. That
# was wrong: deep-context prefill adds ~6.9 GiB of activation memory that
# PyTorch's caching allocator retains rather than returns, which left the real
# margin at +0.06 GiB. Size this against the post-deep-context number, never the
# number you get from a freshly booted idle engine.
#
# What that flag actually does here, which is NOT what its name suggests: because
# --kv-cache-memory-bytes is pinned below, vLLM skips memory profiling entirely
# and logs "This does not respect the gpu_memory_utilization config". So it never
# governs allocation -- it is purely a startup gate that refuses to boot unless
# that fraction of TOTAL device memory is free right now.
#
# That gate is what crash-looped this container 30 times on 08-12: at 0.80 it
# demanded 0.80 x 121.69 = 97.35 GiB free, while qwen3-embed (~13 GiB) and
# sprite-gen (~23 GiB) left only ~76 GiB. It had booted fine on 08-09 only
# because sprite-gen did not start until 08-10 and took the slack afterwards --
# at 0.80 this container could only ever start if it started first. Keeping the
# number honest (0.40) makes the precondition mean something instead of
# reserving a phantom 97 GiB.
#
# Sizing KV to 4 rather than 3 (the --max-num-seqs cap) is deliberate: the spare
# conversation's worth of blocks serves the prefix cache, which shares this pool
# and carries the ~15x warm-turn speedup. Sizing it to exactly 3 would evict
# cached prefixes. Was 19,561,292,085 (6 conversations), and 64.41 GiB before that.
KV_CACHE_BYTES=13040861390   # 12.15 GiB = 4 x 262,144 tokens

# Replace any existing container of the same name. Refuses while requests are in
# flight unless FORCE=1 — a restart drops them mid-generation.
if docker ps -a --format '{{.Names}}' | grep -qx "${NAME}"; then
  if docker ps --format '{{.Names}}' | grep -qx "${NAME}"; then
    running=$(curl -s --max-time 5 "http://localhost:${PORT}/metrics" \
              | awk -F' ' '/^vllm:num_requests_running\{/ {print int($2)}' | head -1)
    running="${running:-0}"
    if [ "${running}" -gt 0 ] && [ "${FORCE:-0}" != "1" ]; then
      echo "REFUSING: ${running} request(s) in flight on :${PORT}." >&2
      echo "Wait for them to drain, or re-run with FORCE=1 to kill them." >&2
      exit 1
    fi
  fi
  echo "Removing existing '${NAME}'..."
  docker rm -f "${NAME}" >/dev/null
  # Wait for the driver to tear down the old CUDA context. Starting immediately
  # after a forced kill races cleanup and fails with
  # "CUDA driver error: operation not permitted" during Triton kernel load.
  echo -n "Waiting for GPU to settle"
  for _ in $(seq 1 30); do
    if [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)" ]; then
      sleep 3; echo " ok"; break
    fi
    echo -n "."; sleep 2
  done
fi

# torch.compile graphs and FlashInfer autotune results are written to
# /root/.cache/vllm. Without a volume there they are rebuilt on every container
# replacement, which is most of a ~12 minute cold boot. Per-backend volume,
# because the cache keys on model + engine config.
#
# On 2026-08-12 the engine died mid-request after 2.5 days of clean uptime and
# stayed down for 8 hours, because this was the only GPU service without a
# restart policy. It must be `unless-stopped`, not `on-failure`: when the vLLM
# engine dies the API server shuts down gracefully and the container exits 0,
# so `on-failure` would never fire.
#
# The command goes through settle-then-serve.sh, which delays a Docker-initiated
# restart long enough for the driver to reclaim the dead CUDA context.
#
# --max-num-seqs is 3 (was 24) to stay under the trigger for that crash. It hit
# in _update_states_after_model_execute -- the MTP accepted-token bookkeeping --
# with exactly 4 requests in the running batch. vLLM issue #35288 reports a CUDA
# fault in that same frame that appears only once the decode batch reaches 4+,
# and #41190 is the same bookkeeping crash on this very model with MTP, still
# open upstream with "disable speculative decoding" as the only known fix.
# Capping the batch at 3 keeps speculative decoding (worth ~2x decode here, at a
# measured acceptance length of 2.2-2.8) instead of paying that price. Requests
# past 3 queue rather than fail. If it crashes again, drop --speculative-config.
#   https://github.com/vllm-project/vllm/issues/35288
#   https://github.com/vllm-project/vllm/issues/41190
docker run -d --gpus all \
  --name "${NAME}" \
  --restart unless-stopped \
  -e HF_HUB_OFFLINE=1 \
  -e CUTE_DSL_ARCH=sm_121a \
  -e VLLM_TARGET_DEVICE=cuda \
  -v "${HOME}/.cache/huggingface:/root/.cache/huggingface" \
  -v vllm-cache-qwen35:/root/.cache/vllm \
  -v "${HERE}/settle-then-serve.sh:/usr/local/bin/settle-then-serve.sh:ro" \
  -p "${PORT}:${PORT}" \
  "${IMAGE}" \
  /usr/local/bin/settle-then-serve.sh \
  vllm serve unsloth/Qwen3.6-35B-A3B-NVFP4 \
    --host 0.0.0.0 --port "${PORT}" \
    --tensor-parallel-size 1 --trust-remote-code \
    --moe-backend auto --linear-backend flashinfer_b12x \
    --attention-backend flashinfer --kv-cache-dtype fp8 \
    --gpu-memory-utilization 0.45 --max-model-len 262144 \
    --kv-cache-memory-bytes "${KV_CACHE_BYTES}" \
    --max-num-seqs 3 --max-num-batched-tokens 32768 \
    --enable-chunked-prefill --async-scheduling \
    --enable-prefix-caching \
    --long-prefill-token-threshold 4096 \
    --speculative-config '{"method":"mtp","num_speculative_tokens":2,"moe_backend":"triton"}' \
    --reasoning-parser qwen3 \
    --default-chat-template-kwargs '{"enable_thinking":true,"preserve_thinking":true}' \
    --tool-call-parser qwen3_coder --enable-auto-tool-choice \
    --override-generation-config '{"temperature":0.6,"top_p":0.95,"top_k":20}'

echo "Started '${NAME}' on :${PORT}. Follow: docker logs -f ${NAME}"
