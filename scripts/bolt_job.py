#!/usr/bin/env python3
"""Offline queue entrypoint: serve Bolt, qualify it, then run the pilot suite.

The host controller applies/restores clock profiles. This job has no privileges.
No package installs, network downloads, Docker commands or host control writes.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path('/workspace')
STOP = threading.Event()
FAILURE = []
CHILDREN = []


def event(label, **data):
    print(json.dumps({'utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                      'event':label, **data}), flush=True)


def terminate():
    for p in CHILDREN:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def guard(out):
    low_count = missing = 0
    with (out/'job-health.jsonl').open('w',buffering=1) as log:
        while not STOP.wait(1):
            zones=[]
            for p in Path('/sys/class/thermal').glob('thermal_zone*/temp'):
                v=read(p)
                if v is not None:
                    try: zones.append(float(v)/1000)
                    except ValueError: pass
            mem={line.split(':',1)[0]:line.split(':',1)[1].strip()
                 for line in (read('/proc/meminfo') or '').splitlines()}
            avail=int(mem['MemAvailable'].split()[0])/1048576 if 'MemAvailable' in mem else None
            sample={'utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                    'monotonic_s':time.monotonic(),'hottest_c':max(zones,default=None),
                    'host_available_gib':avail,
                    'cgroup':{k:read('/sys/fs/cgroup/'+k) for k in
                              ['memory.current','memory.peak','memory.events','cpu.stat']}}
            log.write(json.dumps(sample)+'\n')
            missing=missing+1 if len(zones)<7 or avail is None else 0
            low_count=low_count+1 if avail is not None and avail<8 else 0
            reason=None
            if zones and max(zones)>=95: reason='thermal_limit_95C'
            if low_count>=3: reason='host_memory_below_8GiB_3_samples'
            if missing>=3: reason='required_host_sensors_unavailable_3_samples'
            if reason:
                FAILURE.append(reason)
                event('guard_abort',reason=reason,sample=sample)
                terminate()
                STOP.set()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',choices=['normal','efficiency80'],required=True)
    p.add_argument('--mode',choices=['smoke','suite'],default='smoke')
    p.add_argument('--run-id',required=True)
    p.add_argument('--recipe',choices=['forum','playbook'],default='forum')
    args=p.parse_args()
    if not all(c.isalnum() or c in '-_' for c in args.run_id):
        p.error('Invalid run ID')
    out=ROOT/'results'/args.run_id
    out.mkdir(parents=True,exist_ok=False)
    target=ROOT/'models/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB'
    draft=ROOT/'models/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr'
    if args.recipe=='forum':
        draft=ROOT/'models/forum-LiLiCorr'
    env=os.environ.copy()
    for k,v in {'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HOME':'/workspace/cache/hf',
                'PYTHONDONTWRITEBYTECODE':'1','HF_MODULES_CACHE':'/workspace/cache/hf-modules',
                'XDG_CACHE_HOME':'/workspace/cache','TORCHINDUCTOR_CACHE_DIR':'/workspace/cache/inductor',
                'TRITON_CACHE_DIR':'/workspace/cache/triton','VLLM_CACHE_ROOT':'/workspace/cache/vllm',
                'CUDA_CACHE_PATH':'/workspace/cache/cuda','VLLM_USE_V2_MODEL_RUNNER':'1',
                'VLLM_NO_USAGE_STATS':'1','DO_NOT_TRACK':'1','OMP_NUM_THREADS':'8'}.items(): env[k]=v
    env.pop('HF_TOKEN',None)
    # Isolate compiled artifacts between different runtime builds.
    for key in ['XDG_CACHE_HOME','TORCHINDUCTOR_CACHE_DIR','TRITON_CACHE_DIR',
                'VLLM_CACHE_ROOT','CUDA_CACHE_PATH']:
        env[key]=env[key].replace('/workspace/cache','/workspace/cache/'+args.recipe)
    command=[sys.executable,'-m','vllm.entrypoints.cli.main','serve',str(target),
        '--served-model-name','bolt','--host','127.0.0.1','--port','8000',
        '--trust-remote-code','--load-format','auto','--tensor-parallel-size','1',
        '--max-model-len','32768','--max-num-seqs','4','--gpu-memory-utilization','0.55',
        '--enable-chunked-prefill','--kv-cache-dtype','fp8','--linear-backend','b12x',
        '--moe-backend','b12x','--attention-backend','FLASHINFER','--mamba-backend','flashinfer',
        '--mamba-ssm-cache-dtype','bfloat16','--mamba-cache-dtype','bfloat16',
        '--block-size','64','--prefix-match-unit','64',
        '--enable-mamba-shared-prefix-checkpoint','--seed','42',
        '--limit-mm-per-prompt',json.dumps({'image':1,'video':0}),
        '--enable-auto-tool-choice','--tool-call-parser','qwen3_coder',
        '--reasoning-parser-plugin',str(target/'ultra_v3_reasoning_parser.py'),
        '--reasoning-parser','ultra_v3','--speculative-config',json.dumps({
            'method':'dflash','model':str(draft),'num_speculative_tokens':7,
            'rejection_sample_method':'standard','attention_backend':'FLASHINFER',
            'draft_load_config':{'load_format':'auto'}})]
    if args.recipe=='playbook':
        # Keep the playbook's loader/parser and backend defaults; common resource
        # limits and text workload are held constant across these pilot runs.
        for flag in ['--linear-backend','--moe-backend','--attention-backend',
                     '--mamba-backend','--mamba-ssm-cache-dtype','--mamba-cache-dtype',
                     '--reasoning-parser-plugin']:
            i=command.index(flag); del command[i:i+2]
        command[command.index('--load-format')+1]='instanttensor'
        command[command.index('--reasoning-parser')+1]='nemotron_v3'
        command[command.index('--speculative-config')+1]=json.dumps({
            'method':'dflash','model':str(draft),'num_speculative_tokens':7})
        command+=['--max-num-batched-tokens','4096']
    (out/'launch.json').write_text(json.dumps({'command':command,'profile':args.profile,'recipe':args.recipe,
        'cpu_policies':{str(f):read(f) for f in Path('/sys/devices/system/cpu/cpufreq').glob('policy*/scaling_max_freq')},
        'queue_limits':{'memory_gib':96,'cpu_quota':16,'shm_gib':4},
        'note':'Profile label supplied by host; observed clock telemetry determines actual effect.'},indent=2))
    def stop(*_):
        FAILURE.append('signal')
        STOP.set()
        terminate()
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    watcher=threading.Thread(target=guard,args=(out,),daemon=True)
    watcher.start()
    code=1
    try:
        event('server_start',run_id=args.run_id,profile=args.profile)
        start=time.monotonic()
        with (out/'server.log').open('w',buffering=1) as log:
            server=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            CHILDREN.append(server)
            ready=False
            next_heartbeat=0
            while not STOP.is_set() and server.poll() is None and time.monotonic()-start<1800:
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2) as r:
                        ready=r.status==200
                    if ready: break
                except Exception: pass
                if time.monotonic()>=next_heartbeat:
                    event('waiting_for_server',elapsed_s=round(time.monotonic()-start))
                    next_heartbeat=time.monotonic()+30
                STOP.wait(2)
            if not ready or STOP.is_set():
                FAILURE.append('server_not_ready')
                event('server_failed',exit_code=server.poll())
            else:
                event('server_ready',startup_s=round(time.monotonic()-start,2))
                bench=subprocess.Popen([sys.executable,str(ROOT/'code/bolt_bench.py'),
                    '--out',str(out/'bench'),'--mode',args.mode,'--profile',args.profile],
                    env=env,start_new_session=True)
                CHILDREN.append(bench)
                code=bench.wait()
                if FAILURE: code=1
    finally:
        STOP.set()
        terminate()
        for child in CHILDREN:
            try: child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL)
                child.wait()
        watcher.join(timeout=5)
        (out/'outcome.json').write_text(json.dumps({'exit_code':code,'failures':FAILURE,
            'ended_utc':dt.datetime.now(dt.timezone.utc).isoformat()},indent=2))
        event('job_finished',exit_code=code,failures=FAILURE)
    return code


if __name__=='__main__':
    raise SystemExit(main())
