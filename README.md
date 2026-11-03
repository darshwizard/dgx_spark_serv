# DGX Spark (GB10) — serving & benchmark findings

One NVIDIA DGX Spark, GB10, 121.7 GiB usable unified RAM.

**Run update, November 3:** Qwen 27B completed the new paired comparison.
Nemotron Bolt reached the 90 C thermal stop during normal-clock throughput;
its incomplete run is preserved and has no paired efficiency result. Super VL
and Flash Next are continuing separately. The quality table below still shows
the earlier campaign until the new results and raw records are collected.

**November 3, 2026: new experiments starting now.** Qwen 27B, Nemotron Bolt,
Nemotron Super VL and Qwen Flash Next will be compared at normal settings and
**GPU ceiling 1,800 MHz + CPU 60%**. New measurements are pending; the completed
normal-clock quality results below are retained until replacement results pass
validation. Earlier limited-profile findings are preserved in the deeper reports.

| Requested CPU frequency ceiling | Normal / default | CPU 60% |
|---|---:|---:|
| 10 Cortex-X925 performance cores | 3,900 MHz | 2,340 MHz |
| 10 Cortex-A725 efficiency cores | 2,808 MHz | 1,684.8 MHz |

Normal permits default hardware-managed clocks, not fixed sustained speeds.
The GPU limit is about 60% of the reported 3,003 MHz maximum, and about 75% of
our previously observed ~2,400 MHz normal clock. This is a combined frequency
profile, not a 60% watt limit. CPU settings are requested ceilings; hardware
feedback is logged to check enforcement. CPU affinity and automatic fans stay
unchanged. The models remain loaded across normal/limited profile transitions.

## Headline quality — current 104-scenario tool suite

Quality measures model behavior on the tool suite, using default clock limits.
Power-profile comparisons are presented separately below; differences between
individual quality trials do not establish an effect caused by clock limits.

| Exact checkpoint / serving setup | Quality /100 (points) | Median turn |
|---|---:|---:|
| **[Qwen3.8-Flash-Next-FP4-Local](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-FP4-Local)** + MTP4 | **89** (186/208) | 1.9s |
| **[Qwen3.8-27B-NVFP4](https://huggingface.co/nvidia/Qwen3.8-27B-NVFP4)** + [DFlash2](https://huggingface.co/z-lab/Qwen3.8-27B-DFlash2) | **88** (184/208) | 2.1s |
| **[NVIDIA Nemotron 3.5 Super VL 120B-A12B NVFP4](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4)** + [LiLiCorr](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4-LiLiCorr) | 79 (164/208) | 1.9s |
| **[NVIDIA Nemotron 3.5 Bolt 74B-A9B 24GB](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB)** + [LiLiCorr](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr) | 76 (159/208) | **1.6s** |

Same tool-eval-bench **3.0.1.dev9**, hard mode, seed 42, thinking off. One normal-clock
quality trial per model; a one-point lead is not an established ranking. Safety
findings belong to the model reports, alongside task failures. These are text/tool
tests with mocked document tools; vision and full-window retrieval are unvalidated.

**Which Qwen?** The baseline is a dense **27B** model. Flash Next has a **125B
main model / 6B active per token**, plus **51B n-gram embedding parameters and a
4B MTP head**; its checkpoint is about 96 GiB on disk. Its tables are disk-backed
in this recipe. Bolt's 24GB checkpoint mixes IQ2_XXS experts, NVFP4 Mamba layers,
and Q8_0 embedding/output weights. Draft heads assist generation; they are not
separate quality-test candidates.

## Current experiment and evidence

Each model gets one normal-clock 104-scenario quality trial and four resident,
seeded, exact-length throughput matrices: normal, limited, limited, normal.
Record GPU-reported energy, CPU/GPU temperatures, both fan speeds, memory,
NVMe activity and before/after SSD SMART counters. Stop at the hottest ACPI
zone reaching 90 C or the established memory-pressure thresholds.

**Disk-backed n-gram/PLE tables:** Flash Next continues reading NVMe during
inference. Earlier measurements averaged **61.2 GB host reads and 0.54 GB writes
per ~7.6-minute matrix**, not per answer. These are whole-host counters, not
file-specific attribution; reads do not consume the SSD write-endurance allowance
byte-for-byte. Record storage activity alongside latency, temperature and energy.

New speed/energy headline tables will appear only after all four comparisons
and cleanup validate. No new results are claimed yet. GPU-reported energy is
not whole-machine energy. Quality warnings remain model-behavior findings in
full reports, separate from the frequency comparison.

[Current protocol](docs/CAP1800-PLAN-20261103.txt) ·
[Earlier Super/Flash report](docs/LARGE-MODEL-RESULTS-20261103.txt) ·
[Earlier Qwen/Bolt report](docs/QWEN-BOLT-COMPARISON-20261102.txt) ·
[Serving recipes](docs/LARGE-MODEL-RECIPES-20261103.txt) ·
[Fan and temperature notes](hardware/FAN-OBSERVATIONS-20261102.txt).

**Following this comparison:** long-context usability on real documents/code;
response latency under mixed prefill/decode load; sustained thermals and useful
work per joule. Speculation and KV precision are model-specific investigations,
not standard suite sweeps. No alternative Qwen recipe or cold/warm multi-agent
session study. DeepSeek V4.1 Flash 1017 at 256K context remains last, untested.

---

## Historical LLM benchmarks

The table below preserves earlier runs on the previous installation. **Do not
rank these quality scores against the current 104-scenario table above.**
These historical quality runs use
[tool-eval-bench](https://github.com/SeraphimSerapis/tool-eval-bench) **hard mode**
(v2.5.1.dev30, seed 42, 84 scenarios); all throughput runs use
[llama-benchy](https://github.com/eugr/llama-benchy) (pp2048/tg128, depths 0/4k/8k,
concurrency 1/2/4, 3 runs each). Full chronology, configs, and caveats: [RESULTS.md](RESULTS.md).

> **Benchmarking caveat (see [hardware/](hardware/README.md)):** the historical numbers below were
> taken *after* fixing a firmware power-clamp that silently caps this box at ~15 W. Pre-fix
> figures ran 2–3× low. Always verify GB10 clocks before trusting a throughput number.

## Historical results — August 2026

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

## Historical findings — August 2026

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
