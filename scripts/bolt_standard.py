#!/usr/bin/env python3
"""Run upstream quality and throughput suites in one resident model session."""
import argparse,json,os,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--mode');p.add_argument('--profile');a=p.parse_args();a.out.mkdir(parents=True)
def call(name,cmd):
 (a.out/(name+'-command.json')).write_text(json.dumps(cmd,indent=2))
 print('BEGIN '+name,flush=True)
 with (a.out/(name+'.log')).open('w',buffering=1) as f:
  rc=subprocess.call(cmd,stdout=f,stderr=subprocess.STDOUT)
 print('END '+name+' exit '+str(rc),flush=True)
 if rc:raise SystemExit(rc)
call('quality',['tool-eval-bench','run','--base-url','http://127.0.0.1:8000','--model','bolt','--hardmode','--seed','42','--no-think','--output-dir',str(a.out/'quality')])
cmd=['llama-benchy','--base-url','http://127.0.0.1:8000/v1','--model','bolt','--tokenizer','/workspace/models/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB','--pp','2048','--tg','128','--depth','0','4096','8192','--concurrency','1','2','4','--runs','3','--extra-body','chat_template_kwargs={"enable_thinking":false}','--format','json']
call('throughput-normal',cmd+['--save-result',str(a.out/'throughput-normal.json')])
(a.out/'ready-for-cap').write_text('normal complete; waiting for owner controller clock readback')
for _ in range(1200):
 if (a.out/'cap-applied').exists():break
 time.sleep(1)
else:raise SystemExit('Cap handshake timed out')
call('throughput-efficiency80',cmd+['--save-result',str(a.out/'throughput-efficiency80.json')])
(a.out/'completed').write_text('all suites complete')
