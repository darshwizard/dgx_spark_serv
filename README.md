# DGX Spark (GB10) — serving & benchmark findings

Measurements and recipes from one NVIDIA DGX Spark (GB10, 121.7 GiB usable unified
memory), on a fresh installation. Latest completed tests: **November 3, 2026**.

**Scheduled rerun: November 3, 02:00 EST (07:00 UTC).** All four models will use
fresh normal-clock controls versus **60% GPU clock limit — 1,800 MHz, CPU ceiling
80%**. The completed numbers below still use the earlier 2,402 MHz GPU ceiling.
New headline results will replace them after all reruns complete; raw history stays.

**CPU speeds behind the profile labels** (requested frequency ceilings):

| CPU cores | Normal / default | CPU 80% profile | CPU 60% profile |
|---|---:|---:|---:|
| 10 Cortex-X925 performance cores | 3,900 MHz | 3,120 MHz | 2,340 MHz |
| 10 Cortex-A725 efficiency cores | 2,808 MHz | 2,246.4 MHz | 1,684.8 MHz |

Default means unrestricted up to these reported hardware maxima, not a fixed
clock at all times. Hardware feedback is being logged to check enforcement.
The CPU 60% column defines the new profile; no measurements for it are published
yet. Completed limited-profile results below used CPU 80%.

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

## Paired speed and energy — completed 80% GPU-limit runs

**Coverage:** this paired comparison covers **Super VL and Flash Next only**.
The matched speed/energy protocol has **not yet been run for Bolt or Qwen 27B**.
Their earlier normal/capped throughput tests used different random prompts and
do not establish a paired energy-efficiency result.
[Bolt's existing normal/capped throughput results](docs/BOLT-STANDARD-BENCHMARKS.txt)
· [Qwen 27B's existing normal/capped throughput results](docs/QWEN-BOLT-COMPARISON-20261102.txt).

**Reading the speed columns:** `c` means concurrency: simultaneous requests.

- **c1 decode:** output tokens generated per second with **one active request**;
  this describes single-request generation speed.
- **c4 decode total:** combined output tokens per second across **four active
  requests**. For example, 60 tok/s total is roughly 15 tok/s per request if the
  work is evenly shared; it does not mean 60 tok/s for each request.
- **c1 prefill:** input/prompt tokens processed per second for one request,
  before generating the answer.

| Model / setup | Clocks | c1 decode tok/s | c1 prefill tok/s | c4 decode total tok/s | Full matrix seconds | GPU-reported kJ / matrix |
|---|---|---:|---:|---:|---:|---:|
| Nemotron 3.5 Super VL 120B-A12B NVFP4 + LiLiCorr | Normal — default clocks | 35.4 | 2,185 | 66.4 | 440.2 | 19.53 |
| Nemotron 3.5 Super VL 120B-A12B NVFP4 + LiLiCorr | 80% GPU limit — 2,402 MHz; CPU 80% | 33.7 | 2,196 | 68.4 | 438.9 | 18.54 |
| Qwen3.8-Flash-Next FP4-Local + MTP4 | Normal — default clocks | 39.0 | 1,822 | 59.7 | 453.6 | 17.74 |
| Qwen3.8-Flash-Next FP4-Local + MTP4 | 80% GPU limit — 2,402 MHz; CPU 80% | 38.8 | 1,788 | 59.8 | 459.3 | 17.14 |

Speed columns: depth 0, pp2048, **exactly 128 output tokens**, two passes per
profile × three measured runs. Full matrix: depths **0 / 4K / 8K**, concurrency
**1 / 2 / 4**, with warmups. Energy/time include that whole matrix, its warmups,
and context preparation; they are **not decode-only**. Profiles alternate
**normal → 80% GPU limit → 80% GPU limit → normal**, keeping one server loaded. Both use 20
CPU quota and 32K configured server context. [All shapes and dispersion](experiments/large-models-20261102/throughput-matrix.csv).

**Existing limited profile:** GPU ceiling 2,402 MHz (80% of 3,003 MHz reported maximum),
CPU clock ceilings 80% of hardware maxima. This is a clock limit, not a watt limit.
Observed GPU clocks were already near the ceiling (~2.4 GHz); most of the
frequency reduction was on the CPU. GPU-reported joules are **not whole-machine
energy**; CPU, NVMe, fans and power-supply costs are not fully accounted for.
Different tokenizers also mean equal token counts need not represent equal text.

## What we found

- **Flash Next led this tool suite, narrowly ahead of our 27B baseline.** It
  also had more safety warnings, including cross-tenant disclosure, an injected
  email action and an incorrect payment-success claim. Super improved on Bolt's
  score but did not approach either Qwen. Read the case traces alongside scores.
- **Neither new model won every speed shape.** Flash Next had faster depth-0
  single-request decode; Super had faster prefill and depth-0 aggregate c4 decode.
  At 8K, c4 decode was **31.2 tok/s Super versus 25.9 Flash Next** at normal clocks.
- **Caps modestly reduced measured energy with little change in total time.**
  Super: **5.1% fewer GPU-reported joules**, matrix time essentially unchanged
  (−0.3%). Flash Next: **3.4% fewer joules**, **1.3% longer**. Only two passes per
  profile, on one machine; these are observations, not confidence intervals.
- **Flash Next moves work onto NVMe.** Its matrix averaged **61.2 GB of host
  NVMe reads per pass**, against **<0.3 GB in every Super pass**. Flash used fewer
  GPU-reported joules, but that does not establish a whole-machine efficiency win.
- **A community allocator setting resolved a startup memory spike here.** Stock
  Flash Next initialization crossed our 2 GiB available-RAM stop. Adding
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` to the same pinned recipe
  avoided the failure; the successful campaign's sampled minimum was **17.49 GiB available**.
  We kept the 2 GiB hard floor and 90°C thermal stop. [Evidence and recipes](docs/LARGE-MODEL-RECIPES-20261103.txt).
- **Thermals and fans are recorded.** Full successful-campaign peaks were
  **80.9°C Super / 79.5°C Flash Next**; Flash's peak occurred during startup.
  Capped throughput peaks were **74.7°C / 69.9°C**. Fans remained automatic;
  ambient was unmeasured and Super's first normal pass included fan ramp-up, so
  these are not controlled cooling comparisons. [Fan observations](hardware/FAN-OBSERVATIONS-20261102.txt).
  These peaks refer to the hottest ACPI zone. CPU-labelled zones and the GPU
  can peak at different times; Flash startup showed a 24.3°C CPU-zone lead.
  [Temperature timelines and sensor definitions](docs/THERMAL-HISTORY-20261103.txt).

**Reports and reproducibility:** [Complete new-model report](docs/LARGE-MODEL-RESULTS-20261103.txt)
· [Recipes and startup fixes](docs/LARGE-MODEL-RECIPES-20261103.txt)
· [Protocol](docs/LARGE-MODEL-PROTOCOL-20261102.txt)
· [Readable summaries and raw archives](experiments/large-models-20261102/).
Both jobs completed; model processes were unloaded and the original queue runtime,
reference files and clock limits restored. Firmware and EC settings were unchanged.

**Next planned:** DeepSeek V4.1 Flash 1017, SAGE EXL3 1.62 bpw, tested last with
**256K (262,144-token) configured context**. It has not been downloaded or tested.

## Earlier speed measurements — Qwen 27B and Bolt

| Checkpoint / setup | Normal c1 decode tok/s | Normal c1 prefill tok/s | Normal c4 decode total tok/s |
|---|---:|---:|---:|
| Qwen3.8-27B NVFP4 + DFlash2 | 33.0 | 2,331 | 72.2 |
| Nemotron 3.5 Bolt 74B-A9B 24GB + LiLiCorr | 38.4 | 1,837 | 82.2 |

These used the same current harness family but **random corpus passages, natural
EOS, 16 CPU quota, and one normal-then-capped pass**. They are not matched speed
or efficiency controls for the seeded, fixed-length 20 CPU comparison above.
Their quality scores use the same current 104-scenario suite.
[Qwen versus Bolt report](docs/QWEN-BOLT-COMPARISON-20261102.txt) ·
[Bolt current-suite report](docs/BOLT-STANDARD-BENCHMARKS.txt) ·
[Forum versus NVIDIA runtime pilot](docs/BOLT-RESULTS.txt).

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
