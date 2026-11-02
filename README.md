# DGX Spark (GB10) — serving & benchmark findings

Measurements and recipes from one NVIDIA DGX Spark (GB10, 121 GiB unified
memory). Latest results are from a fresh installation on **November 2, 2026**.

## Headline results — current benchmark suite

| Model / checkpoint | Serving setup | Quality /100 | Median turn | Decode c1 tok/s | Prefill c1 tok/s | Decode c4 aggregate tok/s |
|---|---|---:|---:|---:|---:|---:|
| **[Qwen3.8-27B NVFP4](https://huggingface.co/nvidia/Qwen3.8-27B-NVFP4)** | vLLM + [Qwen3.8-27B-DFlash2](https://huggingface.co/z-lab/Qwen3.8-27B-DFlash2) | **88** (184/208 points) | 2.1s | 33.0 | **2,331** | 72.2 |
| **[NVIDIA Nemotron 3.5 Bolt 74B-A9B 24GB](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB)** | vLLM + [Bolt LiLiCorr](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr) | 76 (159/208 points) | **1.6s** | **38.4** | 1,837 | **82.2** |

**Which models?** Qwen is the dense 27B NVIDIA NVFP4 checkpoint. Bolt has **74B
total / 9B active parameters**, using the **24GB mixed-precision checkpoint**
(IQ2_XXS 2-bit experts, NVFP4 Mamba layers, Q8_0 embedding/output layers).
The small DFlash2 and LiLiCorr models assist generation; they are not separate
quality-test candidates. Both deployments use seven speculative tokens.

**How measured:** same tool-eval-bench **v3.0.1.dev9**, hard mode, **104 scenarios**,
seed 42, thinking off, one quality trial each. Speed columns are normal-clock
llama-benchy **v0.4.1.dev1** means at **pp2048/tg128, depth 0**, three measured
runs per shape. C4 is total throughput across four concurrent requests. Quality
turn latency is from the tool suite, not the throughput test.

## What we found

- **Qwen scored higher on the current tool suite; Bolt had shorter median turns.**
  Qwen passed the sleeper-injection, least-privilege, multi-hop-injection and
  policy-authority cases that Bolt failed. Qwen still had **two safety-critical
  failures**, including another tenant's data disclosure. Neither result supports
  unattended use of consequential tools without application-level controls.
- **Qwen's measured prefill was faster; Bolt's measured decode was faster.**
  The full depth/concurrency matrix matters: Bolt's aggregate c4 decode fell from
  **82.2 tok/s at depth 0 to 35.0 at 8K**; Qwen fell from **72.2 to 28.0**.
  Output rates depend on the text and speculative acceptance; individual samples
  vary substantially. These are observations from two serving recipes, not a
  statistically established universal model ranking.
- **The 80% maximum-clock runs completed with one server kept loaded per model.**
  Random corpus passages and normal-then-capped ordering prevent a causal
  efficiency conclusion. Identical-prompt replays with alternating profiles are
  the next controlled test. GPU clocks already operated near the requested cap.
- **Thermals are measured, not inferred from GPU temperature alone.** Full-campaign
  hottest ACPI readings were **82.8°C for Qwen** and **90.6°C for Bolt**; these
  were different-duration runs with unmeasured ambient, not controlled cooling
  comparisons. [Fan RPM, firmware and sensor findings](hardware/FAN-OBSERVATIONS-20261102.txt).

**Reports, exact pins, raw data and recipes:**
[Qwen versus Bolt comparison](docs/QWEN-BOLT-COMPARISON-20261102.txt) ·
[Bolt current-suite report](docs/BOLT-STANDARD-BENCHMARKS.txt) ·
[Forum versus NVIDIA playbook runtime pilot](docs/BOLT-RESULTS.txt) ·
[Raw Qwen artifacts](experiments/qwen-standard-20261102/) ·
[Raw Bolt artifacts](experiments/bolt-standard-20261102/).
Qwen was tested in supported **text-only mode** after vision initialization hit a
CUDA compatibility error; this does not validate vision serving. Firmware and EC
settings were unchanged. Clock limits and the queue runtime were restored.

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
