# DeepSeek-V4-Flash-0731 EXL3 K2 (2-bit, all 256 experts) on one DGX Spark

Upstream recipe: [tpurtell/deepseek-v4-flash-0731-exl3-k2-spark](https://github.com/tpurtell/deepseek-v4-flash-0731-exl3-k2-spark)
(~84GB weights, vLLM, DSpark drafter, NVFP4 DS-MLA KV). Our measurements on it:
hardmode 88/100 · 2.3s median agent turn · 27 tok/s prose / **52–57 tok/s code**
decode · 1,367 tok/s prefill (flat to depth) · EvalPlus HumanEval+ 88.4.

This directory holds the three local files we layer on the upstream clone, with
the reasoning in their comments. Deploy = clone upstream, drop these in, launch
via `launcher.sh` (or your own single-GPU arbitration).

- **`.env`** — pins `CUTE_DSL_ARCH=sm_121a`, `GPU_MEMORY_UTILIZATION=0.85`,
  `MAX_MODEL_LEN=262144`. None of the three may be empty (CUTE DSL kernel
  compile crashes with a KeyError). Do NOT put flags the entrypoint already
  passes into `EXTRA_VLLM_ARGS`: vLLM is last-wins and a duplicated flag
  silently breaks the tool parser.
- **`compose.override.yaml`** — fixed container name, `restart: "no"`
  (`on-failure` resurrects at boot after an UNCLEAN host death and steals the
  GPU from your arbitration), and a 110g cgroup cap so a leak kills the
  container instead of wedging the box.
- **`launcher.sh`** — in-flight-request guard + GPU-settle wait + compose up.

Known trade-offs from our benches: single-stream lane only (drafter advantage
dies at batch >1; c2 aggregate is BELOW c1); KV = 607k tokens (2.32 × 256k
streams); weakest measured trait is refusal/injection discipline (67% restraint
category; disclosed a planted fake-system directive in a file in 3/3 runs) —
keep untrusted-content handling in your harness.
