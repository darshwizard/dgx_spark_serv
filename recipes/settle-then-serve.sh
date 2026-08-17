#!/usr/bin/env bash
# Wrapper for the qwen35-nvfp4 container command. Does two things before exec'ing
# vLLM, both of them about surviving Docker's `--restart unless-stopped`.
#
# 1. SETTLE. Docker relaunches within ~100ms of the engine dying, but the driver
#    is still tearing down the old CUDA context; starting into it fails with
#    "CUDA driver error: operation not permitted" during Triton kernel load --
#    the same race start-qwen35-nvfp4.sh guards against on manual replacement.
#
# 2. BACK OFF. A restart policy turns any *startup* failure into an unbounded
#    crash loop. On 2026-08-12 a GPU-memory shortfall restarted this container 30
#    times in ~40 minutes. If the previous run died faster than SHORT_RUN_SECONDS
#    it is treated as a failed boot, and the delay doubles each time up to
#    MAX_BACKOFF_SECONDS. A run that lasts longer resets the counter.
#
# State lives in the container's writable layer: it survives a restart but not a
# `docker rm`, so a fresh `docker run` from the start script starts clean and
# without delay (that script does its own GPU-settle poll first).
set -euo pipefail

STAMP=/tmp/.qwen35-last-start
FAILS=/tmp/.qwen35-fail-count
SETTLE_SECONDS="${SETTLE_SECONDS:-45}"
SHORT_RUN_SECONDS="${SHORT_RUN_SECONDS:-300}"
MAX_BACKOFF_SECONDS="${MAX_BACKOFF_SECONDS:-900}"

now="$(date +%s)"

if [ -e "${STAMP}" ]; then
  prev="$(cat "${STAMP}" 2>/dev/null || echo 0)"
  ran=$(( now - prev ))
  fails="$(cat "${FAILS}" 2>/dev/null || echo 0)"

  if [ "${ran}" -lt "${SHORT_RUN_SECONDS}" ]; then
    fails=$(( fails + 1 ))
    delay="${SETTLE_SECONDS}"
    for _ in $(seq 2 "${fails}"); do
      delay=$(( delay * 2 ))
      [ "${delay}" -ge "${MAX_BACKOFF_SECONDS}" ] && { delay="${MAX_BACKOFF_SECONDS}"; break; }
    done
    echo "settle-then-serve: previous run lasted only ${ran}s -- treating as failed boot #${fails}."
    echo "settle-then-serve: check 'docker logs ${HOSTNAME}' for the real error. Backing off ${delay}s..."
  else
    fails=0
    delay="${SETTLE_SECONDS}"
    echo "settle-then-serve: restart after a ${ran}s run; waiting ${delay}s for the driver to reclaim the old CUDA context..."
  fi

  echo "${fails}" > "${FAILS}"
  sleep "${delay}"
  echo "settle-then-serve: proceeding."
fi

echo "${now}" > "${STAMP}"
exec "$@"
