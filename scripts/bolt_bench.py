#!/usr/bin/env python3
"""Small reproducible text/tool benchmark; use inside the queued model job.

This is a pilot workload suite, not tool-eval-bench or a broad intelligence score.
No tools requested by the model are executed. Cold/warm labels are workload
intent: verify prefix-cache metrics before claiming a measured cache hit.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics
import threading
import time
import urllib.request

LOCK = threading.Lock()


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read().decode()


def cgroup():
    out = {}
    for key in ['memory.current', 'memory.peak', 'memory.max', 'memory.events', 'cpu.stat', 'cpu.max']:
        try:
            out[key] = Path('/sys/fs/cgroup', key).read_text().strip()
        except OSError:
            out[key] = None
    return out


def request(base, messages, *, extra=None, limit=256, seed=42):
    body = {'model': 'bolt', 'messages': messages, 'temperature': 0, 'seed': seed,
            'max_tokens': limit, 'stream': True, 'stream_options': {'include_usage': True},
            'chat_template_kwargs': {'enable_thinking': False}}
    body.update(extra or {})
    raw = json.dumps(body).encode()
    row = {'utc_start': utc(), 'monotonic_start': time.monotonic(),
           'request_sha256': hashlib.sha256(raw).hexdigest(), 'request': body,
           'cgroup_before': cgroup(), 'text': '', 'reasoning': '', 'tool_calls': {},
           'usage': None, 'served_model': None, 'finish_reason': None, 'error': None}
    first = last = None
    try:
        req = urllib.request.Request(base+'/v1/chat/completions', data=raw,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=300) as response:
            for line in response:
                if not line.startswith(b'data: '):
                    continue
                payload = line[6:].strip()
                if payload == b'[DONE]':
                    break
                data = json.loads(payload)
                row['served_model'] = data.get('model', row['served_model'])
                if data.get('usage'):
                    row['usage'] = data['usage']
                for choice in data.get('choices', []):
                    if choice.get('finish_reason'):
                        row['finish_reason'] = choice['finish_reason']
                    delta = choice.get('delta', {})
                    if delta.get('content') or delta.get('reasoning_content') or delta.get('reasoning') or delta.get('tool_calls'):
                        last = time.monotonic()
                        if first is None:
                            first = last
                    row['text'] += delta.get('content') or ''
                    row['reasoning'] += delta.get('reasoning_content') or delta.get('reasoning') or ''
                    for tool in delta.get('tool_calls') or []:
                        idx = str(tool.get('index', 0))
                        dest = row['tool_calls'].setdefault(idx, {'name': '', 'arguments': ''})
                        func = tool.get('function', {})
                        dest['name'] += func.get('name') or ''
                        dest['arguments'] += func.get('arguments') or ''
    except Exception as e:
        row['error'] = f'{type(e).__name__}: {e}'
    end = time.monotonic()
    row.update({'utc_end': utc(), 'monotonic_end': end,
                'wall_s': end-row['monotonic_start'],
                'ttft_s': first-row['monotonic_start'] if first else None,
                'decode_interval_s': last-first if first and last else None,
                'cgroup_after': cgroup()})
    tokens = (row['usage'] or {}).get('completion_tokens')
    row['output_tokens_per_wall_s'] = tokens/row['wall_s'] if tokens is not None else None
    # Streaming may batch/buffer tokens: this estimate is explicitly not an engine rate.
    row['stream_decode_tps_estimate'] = ((tokens-1)/(last-first)
        if tokens and tokens>1 and first and last and last>first else None)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', default='http://127.0.0.1:8000')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--mode', choices=['smoke', 'suite'], default='smoke')
    p.add_argument('--profile', required=True)
    p.add_argument('--repeats', type=int, default=3)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    with (args.out/'requests.jsonl').open('w', buffering=1) as log:
        def record(label, prompt, **kwargs):
            row = request(args.base, [{'role': 'user', 'content': prompt}], **kwargs)
            row.update({'label': label, 'profile': args.profile})
            with LOCK:
                rows.append(row)
                log.write(json.dumps(row)+'\n')
            print(json.dumps({'label':label,'wall_s':round(row['wall_s'],2),
                              'usage':row['usage'],'error':row['error']}), flush=True)
            return row
        (args.out/'models.json').write_text(get(args.base+'/v1/models'))
        coherence = record('smoke-capital', 'Reply with only the capital of France.', limit=32)
        tool = {'type':'function','function':{'name':'get_weather','description':'Get weather for a city.',
                 'parameters':{'type':'object','properties':{'city':{'type':'string'}},'required':['city']}}}
        toolrow = record('smoke-tool', 'Use get_weather for Paris.', limit=128,
                         extra={'tools':[tool], 'tool_choice':{'type':'function','function':{'name':'get_weather'}}})
        tool_ok = False
        try:
            calls = list(toolrow['tool_calls'].values())
            tool_ok = len(calls)==1 and calls[0]['name']=='get_weather' and json.loads(calls[0]['arguments'])=={'city':'Paris'}
        except (ValueError, KeyError):
            pass
        gates = {'coherence': coherence['error'] is None and coherence['text'].strip().rstrip('.').lower()=='paris',
                 'tool_parse': toolrow['error'] is None and tool_ok}
        (args.out/'gates.json').write_text(json.dumps(gates,indent=2))
        if not all(gates.values()):
            raise SystemExit('Smoke gate failed; do not report performance as a usable deployment.')
        (args.out/'engine-metrics-initial.txt').write_text(get(args.base+'/metrics'))
        if args.mode=='suite':
            workloads = {
                'prose':'Write a detailed explanation of how rain forms, for an adult beginner. Use at least 500 words.',
                'code':'Write only Python code implementing an LRU cache with get and put, capacity validation, and unit tests. Explain edge cases in comments.',
                'structured':'Return only a JSON array of 100 objects, each with integer id and its square, starting at id 1.'}
            for rep in range(args.repeats):
                for name, prompt in workloads.items():
                    for concurrency in [1,2,4]:
                        start = time.monotonic()
                        # Different first tokens avoid accidental cross-user prefix sharing.
                        with ThreadPoolExecutor(max_workers=concurrency) as pool:
                            batch=list(pool.map(lambda i: record(f'{name}-r{rep}-c{concurrency}-u{i}',
                                f'Benchmark case {rep}-{name}-{concurrency}-{i}.\n'+prompt),range(concurrency)))
                        duration=time.monotonic()-start
                        tokens=sum((r['usage'] or {}).get('completion_tokens',0) for r in batch)
                        with (args.out/'batches.jsonl').open('a') as b:
                            b.write(json.dumps({'workload':name,'rep':rep,'concurrency':concurrency,
                                'wall_s':duration,'tokens':tokens,'aggregate_tokens_per_wall_s':tokens/duration,
                                'errors':sum(r['error'] is not None for r in batch)})+'\n')
                # Exact repeat exposes prefix-cache benefit; cold label requires metric confirmation.
                corpus='\n'.join(f'Record {i}: asset A{i:05d}; owner team{i%17}; count {i%101}.' for i in range(700))
                prompt=f'Long-context trial {rep}.\n'+corpus+'\nReply only with the owner of asset A00699.'
                checks=[]
                for phase in ['cold','repeat']:
                    row=record(f'long-{phase}-r{rep}',prompt,limit=32)
                    checks.append({'label':row['label'],'correct':row['error'] is None and row['text'].strip().rstrip('.').lower()=='team2'})
                with (args.out/'quality.jsonl').open('a') as q:
                    for check in checks: q.write(json.dumps(check)+'\n')
        try:
            (args.out/'engine-metrics-final.txt').write_text(get(args.base+'/metrics'))
        except Exception as e:
            (args.out/'metrics-error.txt').write_text(str(e))
    summary={'profile':args.profile,'mode':args.mode,'requests':len(rows),
             'errors':sum(r['error'] is not None for r in rows),
             'median_wall_s':statistics.median(r['wall_s'] for r in rows),
             'note':'Mixed pilot workloads, not a quality score. See individual requests and batches.'}
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    main()
