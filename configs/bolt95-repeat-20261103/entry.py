#!/usr/bin/env python3
"""Owner-authorized default-clock Bolt thermal repeat; queue only, preserve guards."""
import datetime,hashlib,importlib.util,json,os,re,runpy,shutil,statistics,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
LABEL='bolt-gpu1800normal-02'
def load(name):
 s=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def state(name,**kw):
 p=ROOT/'status.tmp';p.write_text(json.dumps({'state':name,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),**kw},indent=2)+'\n');p.replace(ROOT/'status.json')

def collect(repo,error):
 src=ROOT/LABEL
 if not (src/'job-id').exists():raise RuntimeError('No submitted job; inspect controller failure')
 abort=json.loads((src/'watchdog/abort.json').read_text()) if (src/'watchdog/abort.json').exists() else None
 outcome=json.loads((src/'result/outcome.json').read_text()) if (src/'result/outcome.json').exists() else None
 health=[json.loads(x) for x in (src/'watchdog/health.jsonl').read_text().splitlines()]
 completed=bool(outcome and outcome['exit_code']==0 and (src/'result/bench/completed.json').exists())
 thermal=bool((abort and abort['reason']=='thermal_limit_95C') or (outcome and 'thermal_limit_95C' in outcome.get('failures',[])))
 summary={'completed':completed,'thermal_stop':thermal,'job_id':(src/'job-id').read_text().strip(),'peak_acpi_c':max(x['hottest_c'] for x in health),'thermal_stop_c':95,'normal_clocks':True,'paired_comparison':False,'background_download':'DeepSeek1017 download started concurrently, low CPU/disk priority; actual overlap recorded in host telemetry','controller_error':error,'abort':abort,'outcome':outcome}
 if (src/'result/bench/events.jsonl').exists():
  argv=sys.argv;sys.argv=['workload_energy.py','--events',str(src/'result/bench/events.jsonl'),'--sensors',str(src/'telemetry/sensors.jsonl'),'--out',str(src/'workload-summary.json')]
  try:runpy.run_path(str(repo/'scripts/workload_energy.py'))['main']()
  finally:sys.argv=argv
  work=json.loads((src/'workload-summary.json').read_text())['completed_workloads']
  summary['completed_matrices']=len(work)
  summary['workload_summaries']=work
  if completed:
   assert len(work)==2 and all(x['profile']=='normal' and x['power_coverage_fraction']>=.99 for x in work)
   summary['matrix_seconds_mean']=statistics.mean(x['elapsed_s'] for x in work)
   summary['gpu_kj_mean']=statistics.mean(x['gpu_reported_energy_j'] for x in work)/1000
 sensor_rows=[json.loads(x) for x in (src/'telemetry/sensors.jsonl').read_text().splitlines()]
 bands={}
 for lo,hi in [(0,85),(85,90),(90,93),(93,95),(95,200)]:
  samples=[x for x in sensor_rows if lo<=max(z['celsius'] for z in x['thermal_zones'])<hi]
  fans={}
  for row in samples:
   for hw in row.get('hwmon',[]):
    for name,value in hw.get('sensors',{}).items():
     if name.startswith('fan') and name.endswith('_input') and value.get('raw') is not None:fans.setdefault(hw['id']+'/'+name,[]).append(value['raw'])
  bands[f'{lo}-{hi}C']={'sample_count':len(samples),'fans':{name:{'min_rpm':min(v),'max_rpm':max(v),'mean_rpm':statistics.mean(v)} for name,v in fans.items()}}
 summary['fan_temperature_bands']=bands
 (src/'repeat-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 return summary

def publish(repo,summary):
 src=ROOT/LABEL
 for p in src.rglob('*'):
  if p.is_file() and p.suffix in ['.json','.jsonl','.log','.md'] and re.search(r'hf_[A-Za-z0-9]{25,}|-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----',p.read_text(errors='replace')):raise RuntimeError('Credential-like content in '+str(p))
 env=os.environ.copy();env['GIT_SSH_COMMAND']='ssh -o BatchMode=yes -o IdentityAgent=none'
 subprocess.run(['git','fetch','origin'],cwd=repo,env=env,check=True);subprocess.run(['git','merge','--ff-only','origin/main'],cwd=repo,check=True)
 dest=repo/'experiments/bolt95-repeat-20261103';dest.mkdir(exist_ok=False)
 for name in ['spec.json','job-id','status.json','repeat-summary.json','nvme-smart-before.json','nvme-smart-after.json','workload-summary.json']:
  if (src/name).exists():shutil.copy2(src/name,dest/name)
 for name in ['entry.py','run.py','recover.py','switch-runtime.py','schedule.json']:shutil.copy2(ROOT/name,dest/name)
 with tarfile.open(dest/'raw-run.tar.gz','w:gz') as tf:tf.add(src,arcname=src.name)
 report='Bolt default-clock repeat with95C stop — Nov3,2026\nSame validated Bolt+LiLiCorr7 recipe,32K configured context,20CPU quota,automatic stock fans. Two seeded throughput matrices requested, no repeat quality suite. GPU clock limit reset to defaults before startup; CPU ceilings at hardware maximum. Owner explicitly requested a95C stop for this run only; memory guards unchanged. Default90C retained for all other runs. Firmware/EC settings unchanged.\nConcurrent DeepSeek1017 download was authorized; host-wide CPU/NVMe activity may confound heat, speed and energy. This is a thermal repeat, not a paired comparison against prior limited-only results.\n'+json.dumps(summary,indent=2)+'\nDefaults/runtime restored and model unloaded before publication. GPU-reported joules are not whole-system energy. Interrupted matrix does not establish efficiency.\n'
 (repo/'docs/BOLT95-REPEAT-20261103.txt').write_text(report)
 result=f"stopped again at the **95°C guard** (sampled peak **{summary['peak_acpi_c']:.1f}°C**)" if summary['thermal_stop'] else f"completed both throughput matrices (sampled guard peak **{summary['peak_acpi_c']:.1f}°C**)" if summary['completed'] else 'ended with an infrastructure failure; no complete comparison is available'
 note=f"## Bolt default clocks with a 95°C stop\n\nThe Nov 3 repeat {result}. Stock automatic fans and safety guards were retained. A simultaneous low-priority DeepSeek weight download makes this an observational thermal repeat, **not a paired energy comparison**. [Report and telemetry](docs/BOLT95-REPEAT-20261103.txt) · [Raw evidence](experiments/bolt95-repeat-20261103/).\n\n"
 p=repo/'README.md';text=p.read_text();marker='## Bolt default-clock repeat';assert marker in text;p.write_text(text.replace(marker,note+marker,1))
 manifest={str(p.relative_to(dest)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.rglob('*') if p.is_file()};(dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 subprocess.run(['git','diff','--check'],cwd=repo,check=True);subprocess.run(['git','add','README.md','docs/BOLT95-REPEAT-20261103.txt','experiments/bolt95-repeat-20261103'],cwd=repo,check=True)
 subprocess.run(['git','-c','user.name=Codex','-c','user.email=codex@openai.com','commit','-m','Publish guarded Bolt default-clock thermal repeat'],cwd=repo,check=True);subprocess.run(['git','push','origin','HEAD:main'],cwd=repo,env=env,check=True)

def main():
 cfg=json.loads((ROOT/'schedule.json').read_text());repo=Path(cfg['repo']);control=load('run');control.ROOT=ROOT;control.REPO=repo
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==cfg['source_commit']
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip()
 for p,sha in cfg['host_original_sha256'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha,p
 for name,sha in cfg['controller_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
 for tag,sha in cfg['images'].items():assert subprocess.check_output(['docker','image','inspect',tag,'--format','{{.Id}}'],text=True).strip()==sha,tag
 # Refuse any other queued/running job before altering global clock/runtime state.
 rows=json.loads(control.remote('compute-job status'))['result'];assert not any(x['state'] in ['queued','running'] for x in rows)
 control.remote('mkdir -p ~/workspace/code/cap1800-plans')
 for n in ['model_campaign_job.py','paired_model_bench.py']:subprocess.run(control.SCP+[str(repo/'scripts'/n),control.HOST+':workspace/code/'],check=True)
 subprocess.run(control.SCP+[str(repo/'configs/cap1800-20261103/bolt.json'),control.HOST+':workspace/code/cap1800-plans/'],check=True)
 check="import json,sqlite3; d=sqlite3.connect('file:/var/lib/compute-queue/jobs.db?mode=ro',uri=True); print(json.dumps(d.execute(\"select id from jobs where state in ('running','queued')\").fetchall()))"
 assert not json.loads(subprocess.check_output(['sudo','-n','python3','-c',check],text=True))
 state('running');(ROOT/'runtime-touched').write_text('Owner explicitly authorized default-clock Bolt95C thermal retry\n');error=None
 try:
  subprocess.run(['sudo','-n','nvidia-smi','-rgc'],check=True)
  control.model_run('bolt','02',normal_only=True,thermal_stop_c=95)
 except Exception as e:error=repr(e)
 finally:load('recover').cleanup()
 summary=collect(repo,error);state('publishing',summary=summary);publish(repo,summary)
 state('complete' if summary['completed'] else 'thermal_stopped' if summary['thermal_stop'] else 'failed',summary=summary)
 primary=Path('/home/d_wizard/local-ai/dgx_spark_serv')
 if not subprocess.check_output(['git','status','--porcelain'],cwd=primary,text=True).strip():subprocess.run(['git','pull','--ff-only'],cwd=primary,check=True)
 with Path('/home/d_wizard/local-ai/forum-watch/memory.txt').open('a') as f:f.write('\nBolt default-clock repeat published; status '+str(ROOT/'status.json')+' . DeepSeek download separate.\n')
if __name__=='__main__':
 try:main()
 except BaseException as e:state('failed',error=repr(e));raise
