# DGX Spark (GB10) — serving & benchmark findings

One NVIDIA DGX Spark, GB10, 121.7 GiB usable unified RAM. Latest campaign update:
**November 3, 2026 — normal versus 60% GPU clock limit / CPU 60%.**

**Thermal-stopped comparison — Nemotron 3.5 Bolt 74B-A9B 24GB + LiLiCorr:** the normal-clock run reached the 90 C safety stop (guard peak 90.1 C). Its quality trial completed, but no paired speed/energy result is available. The incomplete run and guard logs are archived; the temperature limit was not raised.

## Model quality — measured at normal clocks

Quality measures task behavior, separately from the clock/energy comparison.
tool-eval-bench 3.0.1.dev9, hard mode, 104 scenarios, seed 42, thinking off;
one quality trial per model. Full reports retain task failures and safety
findings. These tests use text and mocked tools, not real-world tool actions.

| Exact model / setup | Quality /100 (points) | Median turn |
|---|---:|---:|
| [Qwen3.8-27B NVFP4 + DFlash2](https://huggingface.co/nvidia/Qwen3.8-27B-NVFP4) | 88 (184/208) | 2.2s |
| [Nemotron 3.5 Bolt 74B-A9B 24GB + LiLiCorr](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB) | 77 (161/208) | 1.6s |
| [Nemotron 3.5 Super VL 120B-A12B NVFP4 + LiLiCorr](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4) | 80 (167/208) | 1.9s |
| [Qwen3.8-Flash-Next FP4-Local + MTP4](https://huggingface.co/nvidia/Qwen3.8-Flash-Next-FP4-Local) | 89 (185/208) | 1.9s |

Quality differences in a single trial are not an established universal ranking.
Model safety findings are in the full quality reports; they are not attributed
to the clock limit.

## Paired speed, energy and heat — completed comparisons

**Normal:** default CPU/GPU clock limits. **60% GPU clock limit:** GPU ceiling
**1,800 MHz** (about 60% of the reported 3,003 MHz maximum), with CPU frequency
ceilings **60%** of their hardware maxima. CPU affinity stays unchanged. This is
a combined CPU/GPU clock profile, not a 60%-power setting or a GPU-only causal test.

**CPU speeds behind the profile labels** (requested frequency ceilings):

| CPU cores | Normal / default | CPU 60% profile |
|---|---:|---:|
| 10 Cortex-X925 performance cores | 3,900 MHz | 2,340 MHz |
| 10 Cortex-A725 efficiency cores | 2,808 MHz | 1,684.8 MHz |

Default permits operation up to these reported hardware maxima; it does not
mean a fixed clock at all times. Driver requests are distinct from independently
verified hardware clocks; the watchdog records hardware feedback for inspection.
The CPU 60% ceilings are 2,340 MHz for performance cores and 1,684.8 MHz for
efficiency cores. Older limited-profile results remain in the archived reports.

`c` means concurrent requests. **c1 decode** is output tokens/second for one
active request. **c4 decode total** is the combined rate for four simultaneous
requests (60 total is about 15 each if balanced). **Prefill** processes input
tokens before answer generation. The speed columns below use depth 0.

| Model / setup | Profile | c1 decode tok/s | c1 prefill tok/s | c4 decode total tok/s | Full matrix seconds | GPU-reported kJ | Matrix peak ACPI °C |
|---|---|---:|---:|---:|---:|---:|---:|
| Qwen3.8-27B NVFP4 + DFlash2 | Normal | 26.7 | 2,333 | 71.2 | 417.6 | 22.47 | 84.5 |
| Qwen3.8-27B NVFP4 + DFlash2 | 60% GPU limit — 1,800 MHz; CPU 60% | 25.9 | 2,104 | 72.0 | 446.4 | 12.65 | 63.6 |
| Nemotron 3.5 Super VL 120B-A12B NVFP4 + LiLiCorr | Normal | 32.0 | 2,201 | 72.6 | 436.6 | 19.53 | 81.0 |
| Nemotron 3.5 Super VL 120B-A12B NVFP4 + LiLiCorr | 60% GPU limit — 1,800 MHz; CPU 60% | 30.9 | 2,037 | 71.5 | 460.6 | 10.88 | 62.6 |
| Qwen3.8-Flash-Next FP4-Local + MTP4 | Normal | 38.8 | 1,806 | 59.7 | 459.2 | 18.11 | 78.2 |
| Qwen3.8-Flash-Next FP4-Local + MTP4 | 60% GPU limit — 1,800 MHz; CPU 60% | 36.7 | 1,654 | 55.9 | 491.0 | 10.18 | 61.9 |

Seeded llama-benchy 0.4.1.dev1: pp2048, exactly 128 generated tokens in matrix
requests, depth 0/4096/8192, concurrency 1/2/4, three measured runs plus warmup
per shape. Two passes per profile, **Normal → 60% GPU limit → 60% GPU limit →
Normal**, keeping one server loaded. All use 20 CPU quota and 32K configured
context. Prefix cache resets verified before suites; cache/prompt details,
per-pass values and descriptive SD are in the report and raw data.

Energy/time cover the full matrix including warmups and harness probes, whose
small generation overhead can vary. They exclude clock transitions/cooldown.
GPU-reported energy is not whole-machine energy; CPU, NVMe, fans and PSU losses
are not fully accounted for. Different tokenizers also imply different text at
equal token counts. No wall meter or ambient-temperature sensor was available.

## Findings from this campaign

**Disk-backed n-gram/PLE tables:** Flash Next can continue reading NVMe during
inference. The earlier campaign averaged 61.2 GB host reads and 0.54 GB writes
per ~7.6-minute matrix, not per answer. These are whole-host counters; reads
do not consume the SSD write-endurance allowance byte-for-byte. New per-profile
I/O and SMART snapshots are in this campaign’s raw records.

- **Qwen3.8-27B NVFP4 + DFlash2:** GPU-reported matrix energy changed **-43.7%**, and elapsed time **+6.9%**, under the 60% GPU limit / CPU 60% profile.
- **Nemotron 3.5 Super VL 120B-A12B NVFP4 + LiLiCorr:** GPU-reported matrix energy changed **-44.3%**, and elapsed time **+5.5%**, under the 60% GPU limit / CPU 60% profile.
- **Qwen3.8-Flash-Next FP4-Local + MTP4:** GPU-reported matrix energy changed **-43.8%**, and elapsed time **+6.9%**, under the 60% GPU limit / CPU 60% profile.

Only two passes per profile on one host: these are measured observations, not
confidence intervals. Fans remained automatic; starting temperatures, fan speeds
and elapsed-run history matter. Check the fan/temperature timelines before
attributing a temperature difference to a particular component's power.

Flash Next retains the validated `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
startup mitigation. Previous memory-pressure stops and older results remain
archived. No firmware, EC or fan-control changes were made for this experiment.

**Full evidence:** [Campaign report](docs/CAP1800-RESULTS-20261103.txt) ·
[All matrix shapes/SD](experiments/cap1800-20261103/throughput-matrix.csv) ·
[Exact commands, quality reports and raw data](experiments/cap1800-20261103/) ·
[Serving recipes](docs/LARGE-MODEL-RECIPES-20261103.txt) ·
[Fan/cooling notes](hardware/FAN-OBSERVATIONS-20261102.txt).

Models were unloaded and default clock limits and the original queue runtime
restored before publication. DeepSeek V4.1 Flash 1017 SAGE EXL3 1.62 bpw at
**256K configured context** remains a separate planned test, not measured here.

## Earlier results retained for reference

[Earlier Super / Flash 2,402 MHz-limit campaign](docs/LARGE-MODEL-RESULTS-20261103.txt)
· [Earlier Qwen 27B / Bolt comparison](docs/QWEN-BOLT-COMPARISON-20261102.txt).
Those measurements used different clock settings and/or benchmark protocols;
the raw records are preserved rather than overwritten.

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
