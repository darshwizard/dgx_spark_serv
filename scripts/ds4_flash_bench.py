#!/usr/bin/env python3
"""Benchmark ds4-flash (DeepSeek-V4-Flash EXL3 K2, vLLM :8000).

Phases (run one per invocation: coding | concurrency | longctx):
  coding      - 3 coding tasks x {thinking off, thinking on}; TTFT, decode
                tok/s, and objective pass/fail by executing the returned code
                against test cases in a subprocess.
  concurrency - identical-shape generation at c=1,2,4 with distinct prompts
                (so the prefix cache cannot collapse them); per-stream and
                aggregate decode tok/s.
  longctx     - retrieval of 3 planted codenames at ~32k/~120k/~200k prompt
                tokens; prefill tok/s and retrieval score. Escalates only
                while the stability guard passes.

Stability guard between requests: /health answers, container running, host
available memory >= 3 GiB. Any failure aborts the phase nonzero so the
harness (and the operator) sees it instead of a wedged box.

Results: JSON per phase in ./ds4-flash-results/, summary on stdout.
"""
import json, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
import requests

BASE = "http://127.0.0.1:8000"
MODEL = "deepseek-v4-flash-0731-exl3-k2"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ds4-flash-results")
os.makedirs(OUT, exist_ok=True)


def stability_ok(verbose=True):
    try:
        requests.get(f"{BASE}/health", timeout=5).raise_for_status()
    except Exception as e:
        print(f"STABILITY: /health failed: {e}", file=sys.stderr); return False
    st = subprocess.run(["docker", "inspect", "ds4-flash", "--format", "{{.State.Status}}"],
                        capture_output=True, text=True).stdout.strip()
    if st != "running":
        print(f"STABILITY: container state {st!r}", file=sys.stderr); return False
    avail_kb = 0
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable"):
            avail_kb = int(line.split()[1])
    if avail_kb < 3 * 1024 * 1024:
        print(f"STABILITY: only {avail_kb//1024} MiB available", file=sys.stderr); return False
    if verbose:
        print(f"  [guard ok: {avail_kb//1024//1024} GiB available]")
    return True


def chat_stream(messages, thinking=False, max_tokens=1200, timeout=420):
    """Streamed request. Returns dict with ttft, decode_tps, text, usage."""
    body = {"model": MODEL, "messages": messages, "temperature": 0,
            "max_completion_tokens": max_tokens, "stream": True,
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"thinking": thinking}}
    t0 = time.monotonic(); t_first = None; t_last = None
    text, reasoning, usage = [], [], None
    with requests.post(f"{BASE}/v1/chat/completions", json=body, stream=True,
                       timeout=(10, timeout)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line or not line.startswith(b"data: "):
                continue
            payload = line[6:]
            if payload == b"[DONE]":
                break
            d = json.loads(payload)
            if d.get("usage"):
                usage = d["usage"]
            for ch in d.get("choices", []):
                delta = ch.get("delta", {})
                tok = delta.get("content") or delta.get("reasoning_content")
                if tok:
                    now = time.monotonic()
                    if t_first is None:
                        t_first = now
                    t_last = now
                    (reasoning if delta.get("reasoning_content") else text).append(tok)
    comp = usage["completion_tokens"] if usage else 0
    ttft = (t_first - t0) if t_first else None
    decode = (comp - 1) / (t_last - t_first) if (t_first and t_last and t_last > t_first and comp > 1) else None
    return {"ttft_s": round(ttft, 2) if ttft else None,
            "decode_tps": round(decode, 1) if decode else None,
            "wall_s": round(time.monotonic() - t0, 2),
            "completion_tokens": comp,
            "prompt_tokens": usage["prompt_tokens"] if usage else None,
            "reasoning_tokens_approx": len("".join(reasoning)) // 4,
            "text": "".join(text)}


def extract_code(text):
    blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.S)
    return blocks[-1] if blocks else text


def run_tests(code, test_src):
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "sol.py")
        open(p, "w").write(code + "\n\n" + test_src)
        try:
            r = subprocess.run([sys.executable, p], capture_output=True, text=True,
                               timeout=15, cwd=td)
            return ("PASS" if r.returncode == 0 else "FAIL",
                    (r.stderr or r.stdout).strip()[-300:])
        except subprocess.TimeoutExpired:
            return "TIMEOUT", ""


TASKS = [
    ("easy", "Write a Python function `reverse_words(s)` that returns the words of "
             "the string s in reverse order, joined by single spaces. Words are "
             "runs of non-space characters; collapse any amount of whitespace. "
             "Return ONLY one python code block.",
     "assert reverse_words('the sky  is blue') == 'blue is sky the'\n"
     "assert reverse_words('  hello   world  ') == 'world hello'\n"
     "assert reverse_words('a') == 'a'\n"
     "assert reverse_words('') == ''\nprint('ok')"),
    ("medium", "Write a Python class `LRUCache` with `__init__(self, capacity)`, "
               "`get(self, key)` returning the value or -1, and `put(self, key, value)`. "
               "Both get and put count as use for recency; evict the least recently "
               "used key when over capacity. O(1) operations. "
               "Return ONLY one python code block.",
     "c = LRUCache(2)\nc.put(1, 1)\nc.put(2, 2)\nassert c.get(1) == 1\n"
     "c.put(3, 3)\nassert c.get(2) == -1\nc.put(4, 4)\nassert c.get(1) == -1\n"
     "assert c.get(3) == 3\nassert c.get(4) == 4\n"
     "c2 = LRUCache(1)\nc2.put(5, 5)\nc2.put(5, 6)\nassert c2.get(5) == 6\nprint('ok')"),
    ("hard", "Write a Python function `lis(nums)` returning one longest strictly "
             "increasing subsequence of the list nums (the actual elements, in "
             "order), in O(n log n). An empty input returns []. "
             "Return ONLY one python code block.",
     "import random\n"
     "def ref_len(a):\n"
     "    import bisect\n"
     "    tails = []\n"
     "    for x in a:\n"
     "        i = bisect.bisect_left(tails, x)\n"
     "        if i == len(tails): tails.append(x)\n"
     "        else: tails[i] = x\n"
     "    return len(tails)\n"
     "def check(a):\n"
     "    s = lis(a)\n"
     "    assert len(s) == ref_len(a), (a, s)\n"
     "    assert all(s[i] < s[i+1] for i in range(len(s)-1)), s\n"
     "    it = iter(a)\n"
     "    assert all(x in it for x in s), (a, s)\n"
     "check([])\ncheck([5])\ncheck([3,1,2,1,4,0,5])\ncheck([5,4,3,2,1])\n"
     "random.seed(7)\n"
     "for _ in range(50): check([random.randrange(30) for _ in range(random.randrange(0, 60))])\n"
     "print('ok')"),
]


def phase_coding():
    results = []
    for name, prompt, tests in TASKS:
        for thinking in (False, True):
            if not stability_ok():
                return results, "ABORTED"
            label = f"{name}/{'think' if thinking else 'nothink'}"
            print(f"-- {label}")
            r = chat_stream([{"role": "user", "content": prompt}], thinking=thinking,
                            max_tokens=3000 if thinking else 1200)
            verdict, err = run_tests(extract_code(r.pop("text")), tests)
            r.update({"task": label, "tests": verdict, "err": err})
            print(f"   {verdict}  ttft={r['ttft_s']}s decode={r['decode_tps']} tok/s "
                  f"tokens={r['completion_tokens']} wall={r['wall_s']}s")
            results.append(r)
    return results, "OK"


CONC_PROMPTS = [
    "Explain how a B-tree stays balanced during inserts and deletes.",
    "Describe the TCP three-way handshake and what each step guarantees.",
    "Explain how mark-and-sweep garbage collection works and its pauses.",
    "Describe how consistent hashing distributes keys across servers.",
]


def phase_concurrency():
    results = []
    for c in (1, 2, 4):
        if not stability_ok():
            return results, "ABORTED"
        print(f"-- concurrency {c}")
        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=c) as ex:
            outs = list(ex.map(
                lambda p: chat_stream([{"role": "user", "content": p}],
                                      max_tokens=512, timeout=300),
                CONC_PROMPTS[:c]))
        wall = time.monotonic() - t0
        total = sum(o["completion_tokens"] for o in outs)
        per = [o["decode_tps"] for o in outs]
        row = {"c": c, "aggregate_tps": round(total / wall, 1),
               "per_stream_decode_tps": per,
               "ttft_s": [o["ttft_s"] for o in outs],
               "total_tokens": total, "wall_s": round(wall, 1)}
        print(f"   aggregate={row['aggregate_tps']} tok/s  per-stream={per}  ttft={row['ttft_s']}")
        results.append(row)
    return results, "OK"


FACTS = [("subsystem-Aster", "MAGENTA-4217"), ("subsystem-Betel", "COBALT-9034"),
         ("subsystem-Cygnus", "SAFFRON-1188")]

FILLER = ("The scheduler drains its queue before the checkpoint barrier and "
          "re-arms the watchdog. Metrics are flushed on a five second cadence "
          "unless the collector back-pressures, in which case samples are "
          "coalesced and the oldest bucket is dropped first. ")


def build_ctx(target_tokens):
    # ~4.4 chars/token for this filler (measured); overshoot is fine.
    n = int(target_tokens * 4.4 / len(FILLER))
    chunks = [FILLER] * n
    for (name, code), frac in zip(FACTS, (0.20, 0.55, 0.90)):
        chunks.insert(int(len(chunks) * frac),
                      f"\nFor the record, the deployment codename for {name} is {code}.\n")
    return "".join(chunks)


def phase_longctx():
    results = []
    for target in (32_000, 120_000, 200_000):
        if not stability_ok():
            return results, "ABORTED"
        print(f"-- longctx target {target} tokens")
        ctx = build_ctx(target)
        q = ("\n\nFrom the document above, report the deployment codenames for "
             "subsystem-Aster, subsystem-Betel and subsystem-Cygnus, exactly, "
             "as a JSON object mapping subsystem name to codename.")
        try:
            r = chat_stream([{"role": "user", "content": ctx + q}],
                            max_tokens=200, timeout=900)
        except Exception as e:
            print(f"   FAILED: {e}")
            results.append({"target": target, "error": str(e)})
            return results, "ABORTED"
        found = sum(1 for _, code in FACTS if code in r["text"])
        prefill_tps = round(r["prompt_tokens"] / r["ttft_s"], 0) if r["ttft_s"] else None
        row = {"target": target, "prompt_tokens": r["prompt_tokens"],
               "retrieved": f"{found}/3", "prefill_tps": prefill_tps,
               "ttft_s": r["ttft_s"], "decode_tps": r["decode_tps"]}
        print(f"   prompt={r['prompt_tokens']} tok  retrieved={found}/3  "
              f"prefill~{prefill_tps} tok/s  ttft={r['ttft_s']}s")
        results.append(row)
        if found < 3:
            print("   quality dropped; not escalating further")
            return results, "QUALITY_STOP"
    return results, "OK"


if __name__ == "__main__":
    phase = sys.argv[1]
    fn = {"coding": phase_coding, "concurrency": phase_concurrency,
          "longctx": phase_longctx}[phase]
    if not stability_ok():
        sys.exit(2)
    res, status = fn()
    json.dump({"status": status, "results": res},
              open(os.path.join(OUT, f"{phase}.json"), "w"), indent=1)
    print(f"phase {phase}: {status}")
    sys.exit(0 if status in ("OK", "QUALITY_STOP") else 1)
