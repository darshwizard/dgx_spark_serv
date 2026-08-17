# Operating LLMs on a DGX Spark without wedging it

Cross-cutting rules distilled from crashing, hanging, and OOMing one GB10 so you
don't have to. Everything here was learned from a real incident on this box.

## Unified memory changes every rule you know

The 121GB pool is CPU **and** GPU. A model server that over-commits doesn't get a
tidy CUDA OOM — it starves the host, the kernel OOM-killer fires (or doesn't,
and the box hard-hangs), and you're power-cycling. Consequences:

- **Cap every model container**: `--memory 110g --memory-swap 110g` (equal, so it
  can't spill to swap). Better a dead container than a wedged box.
- **`--gpu-memory-utilization` is not what it sounds like.** In vLLM it's a
  fraction of TOTAL device memory that must be FREE AT STARTUP — a boot gate.
  With `--kv-cache-memory-bytes` pinned it never governs allocation at all.
  A container at 0.8 can only ever boot if it boots first.
- **Size KV against post-load reality, not the calculator.** Two of our four
  guest models refused to boot at their published util/context settings because
  our image's non-KV footprint differed from the author's. When KV computes
  negative or below one max-len request: lower `--max-model-len` first (benches
  need ~11k), touch util second.
- **JIT kernel compilation counts too.** FlashInfer JIT-compiling sm_121 modules
  while an 80GB model loads can OOM the host. Warm kernel caches with no weights
  resident.

## One GPU, one tenant, always

- Never launch into a half-released CUDA context. Between models:
  `docker rm -f <old>`, then wait until
  `nvidia-smi --query-compute-apps=pid --format=csv,noheader` is empty, then
  +5s. Launching early fails mid-kernel-load with
  `CUDA driver error: operation not permitted`.
- **`restart: "no"` for every model container** managed by an arbitration
  script. `unless-stopped` seizes the GPU at boot; `on-failure` is sneakier —
  after an UNCLEAN host death docker counts the container as failed and
  resurrects it at boot anyway. If you must auto-restart (a crashy engine),
  cap attempts (`on-failure:2`) and add a settle-delay wrapper so the restart
  doesn't relaunch into the dying CUDA context every 15 seconds.
- Refuse to restart while requests are in flight: check
  `vllm:num_requests_running` / `sglang:num_running_reqs` on /metrics first.

## Trust nothing until probed

Before benchmarking any new serving stack, gate it:
1. **Coherence probe** — one plain question, read the answer with your eyes.
2. **Tool probe** — one forced tool call; require parsed `tool_calls`.
   Failure mode this catches: stacks that chat perfectly but emit token salad
   the moment tools attach (observed on <0.25 vLLM with Laguna S-2.1). A
   harness without this preflight will happily record garbage agentic scores.

## The firmware power clamp (know this one)

GB10s can silently clamp to ~570MHz/15W after crashes (PD-controller fault):
everything still "works," 2–3× slower. Detect: `nvidia-smi -q -d PERFORMANCE`
→ `SW Power Capping` counter growing under load, T.Limit pinned ~50–55°C.
A warm reboot does NOT clear it — full 10-minute AC unplug does. Update EC /
SoC / USB-C-PD firmware (`fwupdmgr`). Any benchmark taken while clamped is
worthless; check clocks before AND after long runs.

## Misc that will bite you

- amd64 images run via qemu binfmt
  (`docker run --privileged --rm tonistiigi/binfmt --install amd64`) — the
  registration does NOT survive reboot.
- `nvidia-smi` reports `memory.used = [N/A]` on GB10 — monitor `free -h` and
  `--query-compute-apps` instead.
- SGLang rejects llama-benchy's default `return_token_ids` with streaming —
  pass `--extra-body 'return_token_ids=false'`.
- Downloads made from inside root containers leave root-owned HF-cache lock
  files that break later user-space downloads; chown via a throwaway container.
