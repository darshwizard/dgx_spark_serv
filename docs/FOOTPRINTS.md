# Memory footprint & concurrency on a 121 GiB DGX Spark

What each tested setup actually costs in the unified pool, and how many users it
serves. The distinction that matters: **on-disk weights** (what you download) vs
**runtime footprint** (weights + KV cache + activation/CUDA-graph/workspace + any
drafter) — the latter is what competes for the 121 GiB shared by CPU and GPU.

Usable budget is ~110 GiB (121 minus ~5–10 for the OS and a few small host
containers).

| model | weights (+drafter) | runtime footprint | max ctx (as run) | KV cache | conc. @ full 262k | ctx for 4 users | tok/s single stream | useful concurrency |
|---|---|---|---|---|---|---|---|---|
| Qwen3.6-35B-A3B NVFP4 | 25 GB (MTP) | **~42–49 GiB** | 262,144 | **12.2 GiB** (1.05M tok, fp8) | 4.0 | 262k each | **77–85** | **scales** — 112 t/s agg @ c3 |
| Qwen3.8-27B NVFP4 (stock) | 21 GB +2.6 | **~50–65 GiB** | 262,144 | within 0.50 pool | ~4 (est.) | — | 25.7 | scales — 65 t/s agg @ c4 |
| Qwen3.8-27B abliterated | 29 GB +2.6 | **~55–70 GiB** | 262,144 | within 0.50 pool | ~4 (est.) | — | 15.5 | scales (40% slower) |
| Muse Glimmer 30B **BF16** | 56 GB | **~60–79 GiB** | 131,072 | within 0.65 gate | — | 4.3 | 1 (4 t/s moot) |
| Ling 3.0 Flash INT4 | 72 GB (NEXTN) | **~80–85 GiB** | 262,144 | fp8, within 0.70 pool | ~2–3 (est.) | — | 28.2 | 1–2 |
| DeepSeek-V4-Flash EXL3 K2 | 79 GB (DSpark) | **~100–103 GiB** | 262,144 | **15.8 GiB** (607k tok) | 2.32 | ~150k each | 27.4 (**52–57 code**) | **1** — batch>1 agg < c1 |
| Laguna-S-2.1 NVFP4 | 93 GB +2.1 | **~100+ GiB** | **65,536** (256k won't fit) | ~4.5 GiB (~132k tok) | 0.5 (can't fit one) | ~33k each | 17.5 | 1–2 |

"within N pool" = the engine (SGLang / util-gated vLLM) bundles KV inside its static
reservation and doesn't report it separately, so only the config bound is known.
tok/s are llama-benchy c1 filler-text decode (conservative floor); DeepSeek's 52–57 is
its *code* decode, where the drafter's high acceptance roughly doubles the filler rate.

## What the numbers say

- **Quality clustered 81–89 across every properly-quantized model; footprint and speed
  varied ~20×.** On this hardware, architecture and quantization decide usability, not
  benchmark IQ.
- **Big footprint buys a bigger/smarter model, not more users.** The ~100 GiB models
  (DeepSeek, Laguna) serve only ~1–2 users: their weights leave little pool for KV, and
  their speculative-decode stacks collapse per-stream throughput at batch >1 (c2 aggregate
  falls *below* c1). These are single-seat orchestrator lanes.
- **Real multi-user serving lives in the ~42–65 GiB A3B tier.** Qwen3.6-35B-A3B and
  Qwen3.8-27B are the only models that both fit multiple full-context streams *and* scale
  aggregate throughput — their few-active-param MoE makes KV cheap (fp8 KV halves it again),
  so four 262k streams fit in ~12 GiB.
- **Context is a footprint dial, not a fixed cost.** Every "262,144" is the ceiling
  allowed, not a mandatory allocation; KV grows with tokens actually in flight. Dropping
  `--max-model-len` is how you reclaim pool for a neighbor.

## Can you co-host two models?

Only the light ones, and only against the arbitration's grain. Workable:
**Qwen3.6-35B-A3B (~45) + Qwen3.8-27B (~55) ≈ 100 GiB** — feasible if you cap both
contexts (64–128k each) to keep KV modest and leave headroom for the graph-capture spike
(SGLang allocates 25–40 GiB of transient, untracked unified memory during CUDA-graph
capture). Anything involving DeepSeek / Laguna / Ling / Muse is effectively exclusive.

Caveat, learned the hard way: the single-GPU arbitration is a scar, not an oversight — a
co-hosting collision (two big models over-committing the shared pool) hard-hangs the box,
with no separate VRAM to fall back on. Treat dual-tenant as a careful experiment with a
stability guard, staggered boots, and hard context caps — not a default.
