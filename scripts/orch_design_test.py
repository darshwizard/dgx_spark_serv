#!/usr/bin/env python3
"""End-to-end test of the RECOMMENDED orchestrator design on ds4-flash.

One episode = the full loop a real orchestrator runs:
  1. main (large warm ctx) writes a plan and dispatches tasks   [decode]
  2. workers execute while main is idle                          [decode x3]
  3. worker reports are appended to main's context; main
     integrates them and concludes                               [prefill+decode]

Two episodes, identical shape, differing only in step 2:
  episode "serial"   - workers run one at a time
  episode "parallel" - all 3 workers run concurrently

Main context is one append-only conversation across both episodes (that is the
pattern; prefix cache carries it). Worker prompts are unique per episode and
per worker (fresh tags), so no cross-stream cache help anywhere.

Compare wall time per episode and per step against each other and against the
naive everything-at-once shape measured in orch_bench.py.
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from ds4_flash_bench import OUT, chat_stream, stability_ok
from orch_bench import corpus, worker_prompt

GEN = 384


def ask(messages, timeout=900):
    return chat_stream(messages, max_tokens=GEN, timeout=timeout)


def slim(r):
    return {k: r[k] for k in ("ttft_s", "decode_tps", "wall_s",
                              "prompt_tokens", "completion_tokens")}


def episode(name, main_msgs, worker_ids, parallel):
    ep = {"mode": name}
    t_ep = time.monotonic()

    # 1. main plans/dispatches
    if not stability_ok(verbose=False): sys.exit(3)
    main_msgs.append({"role": "user", "content":
        f"[{name}] Plan the next investigation round: define three scoped "
        f"sub-tasks (one per worker) and the acceptance criteria for each."})
    r = ask(main_msgs)
    main_msgs.append({"role": "assistant", "content": r["text"]})
    ep["dispatch"] = slim(r)
    print(f"   dispatch: ttft={r['ttft_s']}s decode={r['decode_tps']} "
          f"wall={r['wall_s']}s", flush=True)

    # 2. workers run while main is idle
    t_w = time.monotonic()
    prompts = [worker_prompt(k) for k in worker_ids]
    if parallel:
        with ThreadPoolExecutor(max_workers=3) as ex:
            outs = list(ex.map(lambda p: ask([{"role": "user", "content": p}]),
                               prompts))
    else:
        outs = [ask([{"role": "user", "content": p}]) for p in prompts]
    ep["workers_wall_s"] = round(time.monotonic() - t_w, 1)
    ep["workers"] = [slim(o) for o in outs]
    for k, o in enumerate(outs):
        print(f"   worker{k}: ttft={o['ttft_s']}s decode={o['decode_tps']} "
              f"wall={o['wall_s']}s", flush=True)
    print(f"   workers phase wall={ep['workers_wall_s']}s", flush=True)

    # 3. main ingests the three reports (~1.2k fresh tokens) and integrates
    if not stability_ok(verbose=False): sys.exit(3)
    reports = "\n\n".join(f"=== worker {k} report ===\n{o['text']}"
                          for k, o in enumerate(outs))
    main_msgs.append({"role": "user", "content":
        f"The workers have reported back:\n\n{reports}\n\n"
        f"Integrate the findings and state the round's conclusion."})
    r = ask(main_msgs)
    main_msgs.append({"role": "assistant", "content": r["text"]})
    ep["integrate"] = slim(r)
    ep["episode_wall_s"] = round(time.monotonic() - t_ep, 1)
    print(f"   integrate: ttft={r['ttft_s']}s decode={r['decode_tps']} "
          f"wall={r['wall_s']}s", flush=True)
    print(f"   EPISODE wall={ep['episode_wall_s']}s", flush=True)
    return ep


def main():
    if not stability_ok(): sys.exit(3)
    results = {}

    print("-- setup: build 40k main context (one-time cold prefill)", flush=True)
    tag = "ORCHDESIGN"
    ctx = f"=== orchestrator stream {tag} ===\n" + corpus(tag, 40_000)
    main_msgs = [{"role": "user", "content":
        ctx + f"\nYou are the orchestrator for the {tag} system journal above. "
              f"Acknowledge and summarize its state in three sentences."}]
    r = ask(main_msgs)
    main_msgs.append({"role": "assistant", "content": r["text"]})
    print(f"   setup: ttft={r['ttft_s']}s (prefill "
          f"{round(r['prompt_tokens']/r['ttft_s'])} t/s)", flush=True)
    results["setup"] = slim(r)

    print("-- episode 1: serial workers", flush=True)
    results["serial"] = episode("serial", main_msgs, [31, 32, 33], parallel=False)

    print("-- episode 2: parallel workers", flush=True)
    results["parallel"] = episode("parallel", main_msgs, [41, 42, 43], parallel=True)

    json.dump(results, open(os.path.join(OUT, "orch_design.json"), "w"), indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
