# DGX Spark (GB10) — serving & benchmark findings

Field notes from running one NVIDIA DGX Spark (GB10 Grace-Blackwell, 121 GB unified
memory, aarch64/sm_121a) hard. Two independent tracks:

- **[hardware/](hardware/README.md) — platform, firmware, power, thermals, crashes.**
  Applies to *any* GB10 workload. **Read this first if your Spark is mysteriously slow
  or crashing under load** — this unit shipped with a firmware power fault that a
  `fwupdmgr` update fixed.
- **This page + [docs/](docs/), [recipes/](recipes/) — the LLM serving work below.**

---

## November 2026 Bolt benchmarks

Current tool-eval-bench hard mode: **76/100 on 104 scenarios**, with injection
and action-boundary failures. Current llama-benchy zero-depth decode: **38.4 tok/s
single-stream, 82.2 aggregate at c4**. [Full matrix, reports, and version caveats](docs/BOLT-STANDARD-BENCHMARKS.txt).
The historical Qwen quality score used an older suite and is not directly comparable.

## November 2026 Bolt pilot

Fresh-install comparison of the forum and NVIDIA Spark playbook runtimes, with
normal and 80% maximum-clock profiles: [results and recipes](docs/BOLT-RESULTS.txt).
Both setups completed all pilot requests. These fixed-output throughput tests
are separate from the historical quality and llama-benchy results below.

## Historical LLM benchmarks

Benchmarks of locally-served LLMs. All quality runs use
[tool-eval-bench](https://github.com/SeraphimSerapis/tool-eval-bench) **hard mode**
(v2.5.1.dev30, seed 42, 84 scenarios); all throughput runs use
[llama-benchy](https://github.com/eugr/llama-benchy) (pp2048/tg128, depths 0/4k/8k,
concurrency 1/2/4, 3 runs each). Full chronology, configs, and caveats: [RESULTS.md](RESULTS.md).

> **Benchmarking caveat (see [hardware/](hardware/README.md)):** all numbers here were
> taken *after* fixing a firmware power-clamp that silently caps this box at ~15 W. Pre-fix
> figures ran 2–3× low. Always verify GB10 clocks before trusting a throughput number.

## Headline table

| model | quality (hardmode) | median turn | decode c1 tok/s | prefill c1 tok/s | c4 aggregate |
|---|---|---|---|---|---|
| Qwen3.8-27B NVFP4 (SGLang + DSpark) | **89** | 5.2s | 25.7 | 2,387 | 65.6 |
| DeepSeek-V4-Flash-0731 EXL3 K2 2-bit (vLLM) | 88 | **2.3s** | 27.4 (52–57 on code) | 1,367 | 32.9 |
| Ling 3.0 Flash INT4 124B-A5B (SGLang) | 86 | 4.3s | 28.2 | 2,365 | 44.7 |
| Qwen3.8-27B abliterated NVFP4 (research-only) | 86 | 8.2s | 15.5 | 1,920 | 47.6 |
| Qwen3.6-35B-A3B NVFP4 (vLLM + MTP) | 85 | 2.1s | **77–85** | **5,147–6,344** | ~112* |
| Laguna-S-2.1 NVFP4 (validated cfg) | 83 | 5.5s | 17.5 | 2,450 | 36.9 |
| Laguna-S-2.1 NVFP4 (DFlash + b12x cfg) | 81 | 3.2s | 18.2 | 1,795 | 35.7 |
| Muse Glimmer 30B **BF16** (vLLM) | 81 | 44.0s | 4.3 | 1,376 | 16.3 |

\* seq-capped at 3 concurrent by deployment config.

Also measured for the DeepSeek EXL3 K2: EvalPlus HumanEval+ **88.4** / MBPP+ **74.1**
(greedy, official harness) and standard-suite tool-eval **93/100**.

The abliterated row is a controlled experiment (identical serving to stock Qwen3.8-27B):
abliteration cost only 3 quality points and left core competence intact, but gutted
prompt-injection resistance — Safety & Boundaries fell 92%→65% and it actively followed
planted instructions (activated a cross-turn sleeper injection). Research-only; it loses
exactly the judgment that makes the stock model useful. See RESULTS.md.

## Key findings

1. **Quality clusters (85–89) for every properly-quantized model; speed varies 20×.**
   On unified-memory Blackwell, architecture (active params) and quantization decide
   usability, not benchmark IQ.
2. **Models have personalities on identical scenarios**: DeepSeek EXL3 = flawless
   tool mechanics + weakest refusal/injection discipline; Qwen3.8 = perfect
   restraint/recovery + weakest multi-step execution; Qwen3.6-A3B = 3× speed +
   most safety warnings.
3. **Dense BF16 is bandwidth math, not a bug**: 60 GB of weights over a ~270 GB/s
   bus ≈ 4.5 tok/s. Quantization is mandatory on this hardware class.
4. **Speculative decoding is single-stream-only** on this box: drafter advantage
   dies at batch >1 for every stack tested (DSpark, DFlash, MTP scale >1).
5. **Negative results**: INT4 is the only Ling 3.0 Flash quantization that
   serves on this hardware (every FP4/NVFP4 variant failed — fork-only stacks);
   this Laguna NVFP4 snapshot cannot serve its advertised 256k context on one
   Spark (~122k KV ceiling at util 0.85).

## Contents

- `RESULTS.md` — the full running log (chronological, includes configs and failures)
- `recipes/` — **reusable serving configs, as actually run** (launch scripts with
  the reasoning in comments): DeepSeek EXL3 K2 overlay files, Qwen3.8-27B
  SGLang+DSpark, Qwen3.6-35B-A3B vLLM+MTP (with the measured memory-budget math),
  Laguna S-2.1 both configs (+ the mandatory tool probe), Muse Glimmer BF16, and
  a working/not-working map for every Ling 3.0 Flash quant
- `docs/OPERATIONS.md` — how to run models on unified-memory Blackwell without
  wedging the box: memory caps, restart-policy doctrine, GPU handoff, probe
  gates, the firmware power-clamp check
- `docs/FOOTPRINTS.md` — memory footprint, KV cache, and real concurrency per
  model; why big-footprint models serve few users; the co-hosting analysis
- `docs/GATEWAY.md` — a single-model serving gateway: stable `auto` endpoint that
  survives model swaps, soft-auth identity (apps self-name, no keys to provision),
  reroute-don't-404, caller attribution
- `reports/` — raw tool-eval-bench per-run reports
- `scripts/` — bench harness scripts (coding/concurrency/longctx pair,
  orchestrator-pattern concurrency test, episode-shape test)

Platform, firmware, power, and crash findings are kept separate in
**[hardware/](hardware/README.md)** — they apply to any GB10 workload, not just LLMs.
