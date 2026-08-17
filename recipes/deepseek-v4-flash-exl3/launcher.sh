#!/usr/bin/env bash
# DeepSeek-V4-Flash-0731 EXL3 K2 (all 256 experts) on vLLM -> 127.0.0.1:8000.
#
# Recipe: github.com/tpurtell/deepseek-v4-flash-0731-exl3-k2-spark, cloned in
# ./recipe with local pins in recipe/.env and recipe/compose.override.yaml
# (fixed container name, no boot autostart, 110g memory backstop). Weights
# (~84 GB, wrldsuksgo2mars/DeepSeek-V4-Flash-0731-EXL3-K2-calibrated-v0) are
# revision-pinned by compose.yaml and self-download into ./recipe/data on
# first start -- deliberately NOT ~/.cache/huggingface, so this deployment is
# one directory to keep or delete.
#
# Measured upstream on a single Spark: 1058 t/s prefill; decode 52 t/s on
# code with the dSpark drafter accepting well (63.8%), ~25 t/s when it
# doesn't. Expect the range, not the headline.
#
# EXCLUSIVE tenant: 0.85 of unified memory. Run through `gpu.sh ds4-flash`,
# never directly at boot.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="ds4-flash"
PORT=8000

# Refuse to replace a live server mid-generation unless FORCE=1 -- same rule
# and same SIGPIPE-vs-pipefail workaround as the other launchers.
if docker ps --format '{{.Names}}' | grep -qx "${NAME}"; then
  running=$(curl -s --max-time 5 "http://localhost:${PORT}/metrics" 2>/dev/null \
            | awk '/^vllm:num_requests_running\{/ {print int($2)}' | head -1 || true)
  running="${running:-0}"
  if [ "${running}" -gt 0 ] && [ "${FORCE:-0}" != "1" ]; then
    echo "REFUSING: ${running} request(s) in flight on :${PORT}. FORCE=1 to override." >&2
    exit 1
  fi
fi

# Starting into a half-released CUDA context fails during kernel load.
if [ -n "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)" ]; then
  echo -n "Waiting for GPU to settle"
  for _ in $(seq 1 30); do
    [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)" ] && break
    echo -n "."; sleep 2
  done
  sleep 3; echo " ok"
fi

# --force-recreate so .env/override edits always take effect; up is otherwise
# happy to keep a stale container.
docker compose --project-directory "${HERE}/recipe" up -d --force-recreate

echo "Started '${NAME}' on :${PORT} (host network)."
echo "First start downloads ~84 GB of weights into ${HERE}/recipe/data, then loads."
echo "Follow: docker logs -f ${NAME}   Ready when /health answers on :${PORT}."
