#!/usr/bin/env python3
"""Owner controller: queue only GPU work; profile handshake and fail-closed guard."""
import argparse,datetime as dt,hashlib,json,os,signal,subprocess,time
from pathlib import Path
ROOT=Path('/home/d_wizard/local-ai/large-model-campaign');REPO=Path('/home/d_wizard/local-ai/dgx_spark_serv')
KEY='/home/d_wizard/.ssh/id_ed25519_compute_bench';HOST='agent-bench@192.168.1.240'
SSH=['ssh','-i',KEY,'-o','IdentitiesOnly=yes','-o','BatchMode=yes',HOST]
SCP=['scp','-q','-i',KEY,'-o','IdentitiesOnly=yes']
def run(cmd,**kw):return subprocess.run(cmd,check=True,text=True,**kw)
def remote(cmd):return subprocess.check_output(SSH+[cmd],text=True)
def stamp():return {'utc':dt.datetime.now(dt.timezone.utc).isoformat(),'monotonic_s':time.monotonic()}
def event(name,**kw):print(json.dumps({**stamp(),'event':name,**kw}),flush=True)
def meminfo():return {x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines()}
def hottest():return max(float(p.read_text())/1000 for p in Path('/sys/class/thermal').glob('thermal_zone*/temp'))
def jobstate(jid):return next(x for x in json.loads(remote('compute-job status'))['result'] if x['id']==jid)
def cpu():return {p.name:{k:int((p/k).read_text()) for k in ['scaling_max_freq','cpuinfo_max_freq']} for p in Path('/sys/devices/system/cpu/cpufreq').glob('policy*')}
def gpu():return subprocess.check_output(['nvidia-smi','--query-gpu=clocks.sm,clocks.max.sm,temperature.gpu,power.draw','--format=csv,noheader'],text=True).strip()
def switch(image,label=None):
 cmd=['sudo','python3',str(ROOT/'switch-runtime.py'),image]
 if label:cmd.append(label)
 run(cmd)
 run(['curl','-fsS','--retry','5','--retry-connrefused','--retry-delay','1','http://192.168.1.240:8080/agents'],stdout=subprocess.DEVNULL)
def model_run(model,attempt):
 label=f'{model}-paired-{attempt}';local=ROOT/label;local.mkdir(exist_ok=False)
 jid=None;logger=None;watch=None;active_cap=None;current_profile='normal';handled=0;start=time.monotonic();last_beat=0
 image='super-benchmarks:20261102' if model=='super' else 'flash-benchmarks:20261102'
 switch(image,'Super VL forum image' if model=='super' else 'Flash-Next NVIDIA recipe image')
 try:
  limits=cpu()
  if any(v['scaling_max_freq']!=v['cpuinfo_max_freq'] for v in limits.values()):raise RuntimeError('Unexpected pre-existing CPU cap; refusing to overwrite')
  spec={'command':['python3','/workspace/code/model_campaign_job.py','--model',model,'--run-id',label],
   'metadata':{'commit':subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip(),'dataset':'tool-eval-104-and-seeded-llama-benchy-v2','parameters':{'model':model,'campaign':'large-models-20261102','profiles':['normal','efficiency80','efficiency80','normal'],'exact_output_tokens':128,'numpy_seed':42,'request_seed':42,'context':32768,'cpus':20,'memory_ceiling_gib':118,'source_hashes':{n:hashlib.sha256((REPO/'scripts'/n).read_bytes()).hexdigest() for n in ['model_campaign_job.py','paired_model_bench.py','campaign_guard.py','clock_profile.py']}}}}
  (local/'spec.json').write_text(json.dumps(spec,indent=2));run(SCP+[str(local/'spec.json'),HOST+':workspace/campaign-spec.json'])
  logger=subprocess.Popen(['python3',str(REPO/'scripts/telemetry.py'),'--out',str(local/'telemetry'),'--duration','21600','--label',label],stdout=subprocess.DEVNULL,stderr=open(local/'telemetry.log','w'))
  jid=json.loads(remote('compute-job submit ~/workspace/campaign-spec.json'))['result']['id'];(local/'job-id').write_text(jid)
  watch=subprocess.Popen(['sudo','python3',str(REPO/'scripts/campaign_guard.py'),'--job',jid,'--parent',str(os.getpid()),'--out',str(local/'watchdog')],stdout=open(local/'watchdog-console.log','w'),stderr=subprocess.STDOUT)
  for _ in range(100):
   if (local/'watchdog/armed').exists():break
   if watch.poll() is not None:raise RuntimeError('Watchdog failed to arm')
   time.sleep(.1)
  else:raise RuntimeError('Watchdog arm timeout')
  event('submitted',model=model,job_id=jid,label=label)
  while True:
   status=jobstate(jid);state=status['state'];(local/'status.json').write_text(json.dumps(status,indent=2))
   if state not in ['queued','running']:
    event('job_finished',model=model,state=state,exit_code=status.get('exit_code'));break
   if watch.poll() is not None:
    status=jobstate(jid)
    if status['state'] not in ['queued','running']:break
    raise RuntimeError('Host watchdog exited while job active')
   health=local/'watchdog/health.jsonl'
   if health.exists() and time.time()-health.stat().st_mtime>5:raise RuntimeError('Host watchdog heartbeat missing')
   if time.monotonic()-start>14400:raise RuntimeError('Campaign job exceeded4hours')
   request=remote(f'test ! -f ~/workspace/results/{label}/bench/phase-request.json || cat ~/workspace/results/{label}/bench/phase-request.json').strip()
   if request:
    req=json.loads(request);seq=req['seq'];profile=req['profile']
    if seq>handled:
     if seq!=handled+1 or profile!=['normal','efficiency80','efficiency80','normal'][seq-1]:raise RuntimeError('Invalid profile sequence')
     if profile!=current_profile:
      if profile=='efficiency80':
       active_cap=local/f'phase-{seq}-clocks.json'
       with (local/f'phase-{seq}-clock-apply.log').open('w') as f:run(['sudo','python3',str(REPO/'scripts/clock_profile.py'),'apply','--state',str(active_cap),'--gpu-default-baseline'],stdout=f,stderr=subprocess.STDOUT)
      else:
       with (local/f'phase-{seq}-clock-restore.log').open('w') as f:run(['sudo','python3',str(REPO/'scripts/clock_profile.py'),'restore','--state',str(active_cap)],stdout=f,stderr=subprocess.STDOUT)
       active_cap=None
      current_profile=profile
     event('conditioning',model=model,seq=seq,profile=profile,hottest_c=hottest())
     coolstart=time.monotonic()
     while time.monotonic()-coolstart<30 or (hottest()>60 and time.monotonic()-coolstart<300):
      if (local/'watchdog/abort.json').exists() or watch.poll() is not None:raise RuntimeError('Guard stopped job during conditioning')
      if time.monotonic()-last_beat>30:event('cooldown',model=model,seq=seq,hottest_c=hottest());last_beat=time.monotonic()
      time.sleep(1)
     avail=meminfo()['MemAvailable']
     if avail<3*1024**3:raise RuntimeError('Less than3GiB available at phase admission')
     limits=cpu()
     for v in limits.values():
      if profile=='normal' and v['scaling_max_freq']!=v['cpuinfo_max_freq']:raise RuntimeError('Normal CPU readback mismatch')
      if profile=='efficiency80' and v['scaling_max_freq']>v['cpuinfo_max_freq']*.8:raise RuntimeError('Capped CPU readback mismatch')
     ack={'seq':seq,'profile':profile,'ready':True,**stamp(),'hottest_c':hottest(),'available_gib':avail/1024**3,'cooldown_s':time.monotonic()-coolstart,'temperature_target_met':hottest()<=60,'cpu':limits,'gpu_snapshot':gpu()}
     ackfile=local/f'phase-{seq}-ack.json';ackfile.write_text(json.dumps(ack,indent=2))
     run(SCP+[str(ackfile),HOST+f':workspace/results/{label}/bench/phase-{seq}-ack.tmp'])
     remote(f'mv ~/workspace/results/{label}/bench/phase-{seq}-ack.tmp ~/workspace/results/{label}/bench/phase-{seq}-ack.json')
     event('phase_released',model=model,seq=seq,profile=profile,hottest_c=ack['hottest_c']);handled=seq
   if time.monotonic()-last_beat>30:
    event('heartbeat',model=model,state=state,phase=handled,hottest_c=hottest(),available_gib=meminfo()['MemAvailable']/1024**3);last_beat=time.monotonic()
   time.sleep(3)
  return status['state']=='completed'
 finally:
  if jid:
   status=jobstate(jid)
   if status['state'] in ['queued','running']:remote('compute-job cancel '+jid)
  if active_cap and active_cap.exists():
   with (local/'final-clock-restore.log').open('w') as f:run(['sudo','python3',str(REPO/'scripts/clock_profile.py'),'restore','--state',str(active_cap)],stdout=f,stderr=subprocess.STDOUT)
  if watch:
   try:watch.wait(timeout=5)
   except subprocess.TimeoutExpired:
    run(['sudo','kill','-TERM',str(watch.pid)]);watch.wait(timeout=25)
  if logger:logger.terminate();logger.wait(timeout=20)
  if jid:
   (local/'queue.log').write_text(remote('compute-job logs '+jid))
   if remote(f'test -d ~/workspace/results/{label} && echo yes || true').strip()=='yes':run(SCP+['-r',HOST+':workspace/results/'+label,str(local/'result')])
def main():
 p=argparse.ArgumentParser();p.add_argument('--models',nargs='+',choices=['super','flash'],default=['super','flash']);p.add_argument('--attempt',default='01');a=p.parse_args()
 if not a.attempt.isdigit():raise SystemExit('Numeric attempt required')
 try:
  for model in a.models:
   if not model_run(model,a.attempt):break
 finally:switch('restore')
if __name__=='__main__':main()
