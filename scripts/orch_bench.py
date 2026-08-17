#!/usr/bin/env python3
"""Orchestrator-pattern concurrency bench for ds4-flash.

Models the intended production shape: ONE main stream with large, growing
(append-only) context, plus up to THREE small worker streams it manages.

Cross-stream cache hygiene: every stream gets its own corpus built from a
stream-unique tag woven into every sentence, and each prompt opens with a
stream-unique header line, so no two streams ever share a token prefix. The
main stream's turn-to-turn prefix reuse is deliberately kept -- that reuse IS
the orchestrator pattern -- and scenarios that benefit from it are labeled
warm.

Scenarios (stability guard between each; abort on failure):
  warmup                 4-way tiny batched call; pays the one-time CUDA graph
                         capture so it never pollutes a measurement.
  worker_solo            one 2k-context worker alone: baseline TTFT + decode.
  main_solo_cold         main stream, ~40k fresh context: cold prefill + decode.
  main_solo_warm         next turn on the same context: warm TTFT + decode.
  mixed_decode           main warm turn + 3 fresh workers at once: per-stream
                         decode vs the solo baselines.
  worker_during_prefill  main turn appending ~20k FRESH tokens (real chunked
                         prefill), workers fired 2s in: worker TTFT/decode
                         while the big prefill is in flight.

Results: ds4-flash-results/orchestrator.json, summary on stdout.
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from ds4_flash_bench import BASE, OUT, chat_stream, stability_ok

GEN_TOKENS = 384

ADJ = ["amber", "brisk", "coiled", "dormant", "etched", "fervent", "gilded",
       "hollow", "inert", "jagged", "keen", "lucid", "molten", "nimble"]
NOUN = ["ledger", "conduit", "turbine", "archive", "beacon", "lattice",
        "reservoir", "manifold", "spindle", "vault", "relay", "prism"]
VERB = ["stalls", "drifts", "saturates", "rebounds", "decays", "fractures",
        "aligns", "overflows", "settles", "ignites", "wanders", "converges"]


def corpus(tag, target_tokens):
    """Deterministic filler unique to `tag`; ~4.5 chars/token measured."""
    off = sum(ord(c) for c in tag)
    out, i = [], 0
    # ~9 tokens/sentence; overshoot slightly, usage reports the truth.
    while sum(len(s) for s in out) < target_tokens * 4.5:
        a = ADJ[(off + i) % len(ADJ)]
        n = NOUN[(off + 3 * i) % len(NOUN)]
        v = VERB[(off + 7 * i) % len(VERB)]
        out.append(f"{tag} entry {i}: the {a} {n} {v} before checkpoint {i % 97}. ")
        i += 1
    return "".join(out)


def worker_prompt(k):
    tag = f"WRK{k}"
    return (f"=== worker stream {tag} ===\n" + corpus(tag, 2000) +
            f"\nSummarize the recurring failure modes in the {tag} log above "
            f"and propose a mitigation plan. Be thorough.")


def ask(messages, timeout=900):
    return chat_stream(messages, max_tokens=GEN_TOKENS, timeout=timeout)


def report(label, r):
    print(f"   {label}: ttft={r['ttft_s']}s decode={r['decode_tps']} tok/s "
          f"prompt={r['prompt_tokens']} completion={r['completion_tokens']} "
          f"wall={r['wall_s']}s", flush=True)


def main():
    results = {}
    guard = lambda: stability_ok() or sys.exit(3)

    # -- warmup: unique throwaway prompts, batch of 4, graph capture --------
    guard()
    print("-- warmup (4-way, throwaway)", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(lambda k: chat_stream(
            [{"role": "user", "content": f"WARM{k}: name {k+2} prime numbers."}],
            max_tokens=32, timeout=120), range(4)))

    # -- worker baseline ----------------------------------------------------
    guard()
    print("-- worker_solo", flush=True)
    r = ask([{"role": "user", "content": worker_prompt(9)}])
    report("worker", r); r.pop("text")
    results["worker_solo"] = r

    # -- main baseline: cold then warm -------------------------------------
    guard()
    print("-- main_solo_cold (~40k fresh context)", flush=True)
    tag = "MAINSTREAM"
    ctx = f"=== orchestrator stream {tag} ===\n" + corpus(tag, 40_000)
    main_msgs = [{"role": "user", "content":
                  ctx + f"\nYou are the orchestrator reading the {tag} journal "
                        f"above. Outline the system's overall health."}]
    r = ask(main_msgs)
    main_msgs.append({"role": "assistant", "content": r["text"]})
    report("main cold", r); r.pop("text")
    r["prefill_tps"] = round(r["prompt_tokens"] / r["ttft_s"]) if r["ttft_s"] else None
    results["main_solo_cold"] = r

    guard()
    print("-- main_solo_warm (turn 2, same context)", flush=True)
    main_msgs.append({"role": "user", "content":
                      "Now list the three most overloaded components, with evidence."})
    r = ask(main_msgs)
    main_msgs.append({"role": "assistant", "content": r["text"]})
    report("main warm", r); r.pop("text")
    results["main_solo_warm"] = r

    # -- mixed decode: main warm turn + 3 fresh workers ---------------------
    guard()
    print("-- mixed_decode (main warm turn + 3 workers)", flush=True)
    main_msgs.append({"role": "user", "content":
                      "Draft a maintenance schedule addressing those components."})
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as ex:
        fm = ex.submit(ask, main_msgs)
        fw = [ex.submit(ask, [{"role": "user", "content": worker_prompt(k)}])
              for k in range(3)]
        rm, rw = fm.result(), [f.result() for f in fw]
    wall = time.monotonic() - t0
    main_msgs.append({"role": "assistant", "content": rm["text"]})
    report("main  ", rm); rm.pop("text")
    for k, r in enumerate(rw):
        report(f"work-{k}", r); r.pop("text")
    total = rm["completion_tokens"] + sum(r["completion_tokens"] for r in rw)
    results["mixed_decode"] = {"main": rm, "workers": rw,
                               "aggregate_tps": round(total / wall, 1),
                               "wall_s": round(wall, 1)}
    print(f"   aggregate={results['mixed_decode']['aggregate_tps']} tok/s", flush=True)

    # -- workers arriving mid-prefill ---------------------------------------
    guard()
    print("-- worker_during_prefill (main appends ~20k fresh, workers +2s)", flush=True)
    fresh = corpus("MAINSTREAM-PHASE2", 20_000)
    main_msgs.append({"role": "user", "content":
                      "A new journal segment follows.\n" + fresh +
                      "\nRevise the overall health assessment in light of it."})
    with ThreadPoolExecutor(max_workers=4) as ex:
        fm = ex.submit(ask, main_msgs)
        time.sleep(2.0)
        fw = [ex.submit(ask, [{"role": "user", "content": worker_prompt(k + 20)}])
              for k in range(3)]
        rm, rw = fm.result(), [f.result() for f in fw]
    rm.pop("text")
    report("main  ", rm)
    for k, r in enumerate(rw):
        report(f"work-{k}", r); r.pop("text")
    results["worker_during_prefill"] = {"main": rm, "workers": rw}

    guard()
    json.dump(results, open(os.path.join(OUT, "orchestrator.json"), "w"), indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
