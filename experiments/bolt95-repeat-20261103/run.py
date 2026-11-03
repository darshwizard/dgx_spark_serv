#!/usr/bin/env python3
"""Owner controller: queue only GPU work; profile handshake and fail-closed guard."""
import argparse,datetime as dt,hashlib,json,os,re,signal,subprocess,time
from pathlib import Path
ROOT=Path('/home/d_wizard/local-ai/cap1800-20261103');REPO=Path('/home/d_wizard/local-ai/dgx_spark_serv')
KEY='/home/d_wizard/.ssh/id_ed25519_compute_bench';HOST='agent-bench@192.168.1.240'
SSH=['ssh','-i',KEY,'-o','IdentitiesOnly=yes','-o','BatchMode=yes',HOST]
SCP=['scp','-q','-i',KEY,'-o','IdentitiesOnly=yes']
def run(cmd,**kw):return subprocess.run(cmd,check=True,text=True,**kw)
def remote(cmd):return subprocess.check_output(SSH+[cmd],text=True)
def stamp():return {'utc':dt.datetime.now(dt.timezone.utc).isoformat(),'monotonic_s':time.monotonic()}
def event(name,**kw):print(json.dumps({**stamp(),'event':name,**kw}),flush=True)
def smart_snapshot(folder,name):
 data=subprocess.check_output(['sudo','-n','/usr/sbin/nvme','smart-log','/dev/nvme0','-o','json'],text=True,timeout=10)
 (folder/name).write_text(json.dumps({'utc':stamp()['utc'],'device':'/dev/nvme0','smart':json.loads(data)},indent=2)+'\n')
def meminfo():return {x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines()}
def hottest():return max(float(p.read_text())/1000 for p in Path('/sys/class/thermal').glob('thermal_zone*/temp'))
def jobstate(jid):return next(x for x in json.loads(remote('compute-job status'))['result'] if x['id']==jid)
def cpu():return {p.name:{k:int((p/k).read_text()) for k in ['scaling_max_freq','cpuinfo_max_freq']} for p in Path('/sys/devices/system/cpu/cpufreq').glob('policy*')}
def gpu():return subprocess.check_output(['nvidia-smi','--query-gpu=clocks.sm,clocks.max.sm,temperature.gpu,power.draw','--format=csv,noheader'],text=True).strip()
def switch(image,label=None,thermal_stop_c=90):
 cmd=['sudo','-n','python3',str(ROOT/'switch-runtime.py'),image]
 if label:cmd.extend([label,str(thermal_stop_c)])
 run(cmd)
 run(['curl','-fsS','--retry','5','--retry-connrefused','--retry-delay','1','http://192.168.1.240:8080/agents'],stdout=subprocess.DEVNULL)
def run_label(model,attempt,limited_only=False,normal_only=False):
 if limited_only and normal_only:raise ValueError('Conflicting phase modes')
 if model not in ['qwen27','bolt','super','flash'] or not re.fullmatch('[0-9]+',attempt):raise ValueError('Invalid model or attempt')
 return f'{model}-gpu1800{"limited" if limited_only else "normal" if normal_only else ""}-{attempt}'
def model_run(model,attempt,limited_only=False,normal_only=False,thermal_stop_c=90):
 if thermal_stop_c not in [90,95]:raise ValueError("Unsupported thermal stop")
 phases=['normal']*2 if normal_only else ['gpu1800_cpu60']*2 if limited_only else ['normal','gpu1800_cpu60','gpu1800_cpu60','normal']
 label=run_label(model,attempt,limited_only,normal_only)
 # Refuse stale remote output before changing clocks/runtime or submitting work.
 if remote(f'test -e ~/workspace/results/{label} && echo exists || true').strip():raise RuntimeError('Remote run output already exists: '+label)
 local=ROOT/label;local.mkdir(exist_ok=False)
 jid=None;logger=None;watch=None;active_cap=None;current_profile='normal';handled=0;start=time.monotonic();last_beat=0
 image={'qwen27':'qwen-benchmarks:20261102','bolt':'bolt-benchmarks:20261102','super':'super-benchmarks:20261102','flash':'flash-benchmarks:20261102'}[model]
 switch(image,{'qwen27':'Qwen 27B NVIDIA image','bolt':'Bolt NVIDIA playbook image','super':'Super VL forum image','flash':'Flash-Next NVIDIA recipe image'}[model],thermal_stop_c)
 try:
  limits=cpu()
  if any(v['scaling_max_freq']!=v['cpuinfo_max_freq'] for v in limits.values()):raise RuntimeError('Unexpected pre-existing CPU cap; refusing to overwrite')
  spec={'command':['python3','/workspace/code/model_campaign_job.py','--thermal-stop-c',str(thermal_stop_c),'--model',model,'--run-id',label,'--limited-profile','gpu1800_cpu60','--quality-mode','normal-only','--phase-mode','normal-only' if normal_only else 'limited-only' if limited_only else 'paired'],
   'metadata':{'commit':subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip(),'dataset':'tool-eval-104-and-seeded-llama-benchy-v2','parameters':{'model':model,'thermal_stop_c':thermal_stop_c,'campaign':ROOT.name,'profiles':phases,'exact_output_tokens':128,'numpy_seed':42,'request_seed':42,'context':32768,'cpus':20,'memory_ceiling_gib':118,'gpu_ceiling_mhz':None if normal_only else 1800,'cpu_ceiling_fraction':1.0 if normal_only else 0.6,'quality_mode':'none' if limited_only or normal_only else 'normal-only','source_hashes':{n:hashlib.sha256((REPO/'scripts'/n).read_bytes()).hexdigest() for n in ['model_campaign_job.py','paired_model_bench.py','campaign_guard.py','clock_profile.py']}}}}
  (local/'spec.json').write_text(json.dumps(spec,indent=2));run(SCP+[str(local/'spec.json'),HOST+':workspace/campaign-spec.json'])
  smart_snapshot(local,'nvme-smart-before.json')
  logger=subprocess.Popen(['python3',str(REPO/'scripts/telemetry.py'),'--out',str(local/'telemetry'),'--duration','21600','--label',label],stdout=subprocess.DEVNULL,stderr=open(local/'telemetry.log','w'))
  jid=json.loads(remote('compute-job submit ~/workspace/campaign-spec.json'))['result']['id'];(local/'job-id').write_text(jid)
  watch=subprocess.Popen(['sudo','-n','python3',str(REPO/'scripts/campaign_guard.py'),'--job',jid,'--thermal-stop-c',str(thermal_stop_c),'--parent',str(os.getpid()),'--out',str(local/'watchdog')],stdout=open(local/'watchdog-console.log','w'),stderr=subprocess.STDOUT)
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
     if seq!=handled+1 or profile!=phases[seq-1]:raise RuntimeError('Invalid profile sequence')
     if profile!=current_profile:
      if profile=='gpu1800_cpu60':
       active_cap=local/f'phase-{seq}-clocks.json'
       with (local/f'phase-{seq}-clock-apply.log').open('w') as f:run(['sudo','-n','python3',str(REPO/'scripts/clock_profile.py'),'apply','--state',str(active_cap),'--gpu-default-baseline','--gpu-max-mhz','1800','--cpu-max-fraction','0.6'],stdout=f,stderr=subprocess.STDOUT)
      else:
       with (local/f'phase-{seq}-clock-restore.log').open('w') as f:run(['sudo','-n','python3',str(REPO/'scripts/clock_profile.py'),'restore','--state',str(active_cap)],stdout=f,stderr=subprocess.STDOUT)
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
      if profile=='gpu1800_cpu60' and v['scaling_max_freq']>v['cpuinfo_max_freq']*.6:raise RuntimeError('Capped CPU readback mismatch')
     if profile=='gpu1800_cpu60' and int(gpu().split(' MHz')[0])>1800:raise RuntimeError('GPU ceiling did not settle before phase release')
     ack={'gpu_ceiling_mhz':1800 if profile=='gpu1800_cpu60' else None,'cpu_ceiling_fraction':0.6 if profile=='gpu1800_cpu60' else 1.0,'seq':seq,'profile':profile,'ready':True,**stamp(),'hottest_c':hottest(),'available_gib':avail/1024**3,'cooldown_s':time.monotonic()-coolstart,'temperature_target_met':hottest()<=60,'cpu':limits,'gpu_snapshot':gpu()}
     ackfile=local/f'phase-{seq}-ack.json';ackfile.write_text(json.dumps(ack,indent=2))
     run(SCP+[str(ackfile),HOST+f':workspace/results/{label}/bench/phase-{seq}-ack.tmp'])
     remote(f'mv ~/workspace/results/{label}/bench/phase-{seq}-ack.tmp ~/workspace/results/{label}/bench/phase-{seq}-ack.json')
     event('phase_released',model=model,seq=seq,profile=profile,hottest_c=ack['hottest_c']);handled=seq
   if current_profile=='gpu1800_cpu60' and int(gpu().split(' MHz')[0])>1800:raise RuntimeError('Observed GPU clock above 1800 MHz ceiling')
   if time.monotonic()-last_beat>30:
    event('heartbeat',model=model,state=state,phase=handled,hottest_c=hottest(),available_gib=meminfo()['MemAvailable']/1024**3);last_beat=time.monotonic()
   time.sleep(3)
  return status['state']=='completed'
 finally:
  if jid:
   status=jobstate(jid)
   if status['state'] in ['queued','running']:remote('compute-job cancel '+jid)
  if active_cap and active_cap.exists():
   with (local/'final-clock-restore.log').open('w') as f:run(['sudo','-n','python3',str(REPO/'scripts/clock_profile.py'),'restore','--state',str(active_cap)],stdout=f,stderr=subprocess.STDOUT)
  if watch:
   try:watch.wait(timeout=5)
   except subprocess.TimeoutExpired:
    run(['sudo','-n','kill','-TERM',str(watch.pid)]);watch.wait(timeout=25)
  if logger:logger.terminate();logger.wait(timeout=20)
  smart_snapshot(local,'nvme-smart-after.json')
  if jid:
   (local/'queue.log').write_text(remote('compute-job logs '+jid))
   if remote(f'test -d ~/workspace/results/{label} && echo yes || true').strip()=='yes':run(SCP+['-r',HOST+':workspace/results/'+label,str(local/'result')])
def main():
 p=argparse.ArgumentParser();p.add_argument('--models',nargs='+',choices=['qwen27','bolt','super','flash'],default=['qwen27','bolt','super','flash']);p.add_argument('--attempt',default='01');a=p.parse_args()
 if not a.attempt.isdigit():raise SystemExit('Numeric attempt required')
 try:
  for model in a.models:
   if not model_run(model,a.attempt):break
 finally:switch('restore')
if __name__=='__main__':main()
