#!/usr/bin/env python3
"""Resident-server quality and seeded throughput, normal/capped/capped/normal.

Owner controller acknowledges each phase only after clock readback and cooldown.
No privileged host operation is performed by this script or the model job.
"""
import argparse,datetime as dt,json,subprocess,sys,time,urllib.request
from pathlib import Path
BASE='http://127.0.0.1:8000'
def stamp():return {'utc':dt.datetime.now(dt.timezone.utc).isoformat(),'monotonic_s':time.monotonic()}
def get(path):
 with urllib.request.urlopen(BASE+path,timeout=20) as r:return r.read().decode()
def reset_cache():
 for attempt in range(5):
  req=urllib.request.Request(BASE+'/reset_prefix_cache',data=b'',method='POST')
  with urllib.request.urlopen(req,timeout=60) as r:
   body=r.read().decode()
   if r.status!=200:raise RuntimeError('Prefix cache reset was not accepted')
   result=json.loads(body)
   if result.get('success') is True:return {'status':r.status,'body':body,'attempts':attempt+1}
   if result.get('success') is not False:raise RuntimeError('Unknown prefix cache reset response: '+body)
  time.sleep(1)
 raise RuntimeError('Prefix cache remained busy after five reset attempts')
def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--tokenizer',required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
 with (a.out/'events.jsonl').open('w',buffering=1) as ledger:
  def event(label,**kw):
   row={**stamp(),'event':label,**kw};ledger.write(json.dumps(row)+'\n');print(json.dumps(row),flush=True)
  def run(label,cmd,folder):
   (folder/(label+'-command.json')).write_text(json.dumps(cmd,indent=2))
   (folder/(label+'-metrics-before.txt')).write_text(get('/metrics'))
   event('workload_start',label=label)
   with (folder/(label+'.log')).open('w',buffering=1) as f:rc=subprocess.call(cmd,stdout=f,stderr=subprocess.STDOUT)
   event('workload_end',label=label,exit_code=rc)
   (folder/(label+'-metrics-after.txt')).write_text(get('/metrics'))
   if rc:raise RuntimeError(label+' failed with exit code '+str(rc))
  (a.out/'models.json').write_text(get('/v1/models'))
  for seq,profile in enumerate(['normal','efficiency80','efficiency80','normal'],1):
   folder=a.out/f'phase-{seq}-{profile}';folder.mkdir()
   request={'seq':seq,'profile':profile,**stamp()};tmp=a.out/'phase-request.tmp';tmp.write_text(json.dumps(request));tmp.replace(a.out/'phase-request.json')
   reply=a.out/f'phase-{seq}-ack.json';event('waiting_for_profile',**request)
   start=time.monotonic()
   while not reply.exists():
    if time.monotonic()-start>1800:raise TimeoutError('Host profile handshake timed out')
    time.sleep(1)
   ack=json.loads(reply.read_text())
   if ack.get('seq')!=seq or ack.get('profile')!=profile or not ack.get('ready'):raise RuntimeError('Invalid profile acknowledgement')
   (folder/'profile-ack.json').write_text(json.dumps(ack,indent=2))
   event('profile_ready',seq=seq,profile=profile,ack=ack)
   if seq in [1,2]:
    (folder/'quality-cache-reset.json').write_text(json.dumps(reset_cache()))
    run('quality',['tool-eval-bench','run','--base-url',BASE,'--model','candidate','--hardmode','--seed','42','--no-think','--output-dir',str(folder/'quality')],folder)
   (folder/'throughput-cache-reset.json').write_text(json.dumps(reset_cache()))
   # NumPy chooses corpus offsets upstream. Reset it identically for EVERY
   # invocation; no UUID/no-cache noise, and reset server prefix cache above.
   # Fixed output length + request seed make workload/accounting reproducible.
   cmd=[sys.executable,'-c','import numpy as np; np.random.seed(42); from llama_benchy.__main__ import main; main()',
    '--base-url',BASE+'/v1','--model','candidate','--tokenizer',a.tokenizer,
    '--pp','2048','--tg','128','--exact-tg','--depth','0','4096','8192',
    '--concurrency','1','2','4','--runs','3','--warmup-runs','1',
    '--extra-body','chat_template_kwargs={"enable_thinking":false}','--extra-body','seed=42',
    '--format','json','--save-result',str(folder/'throughput.json')]
   run('throughput',cmd,folder)
   (folder/'completed.json').write_text(json.dumps(stamp()))
  (a.out/'completed.json').write_text(json.dumps(stamp()));event('all_phases_complete')
if __name__=='__main__':main()
