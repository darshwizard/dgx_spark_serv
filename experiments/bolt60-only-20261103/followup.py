#!/usr/bin/env python3
"""Durable follow-up: wait for the active campaign, then queue Bolt limited-only."""
import datetime,hashlib,importlib.util,json,os,shutil,statistics,subprocess,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
WAIT_FOR='spark-bench-1800-cpu60-continue-20261103.service'
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def state(name,**kw):
 p=ROOT/'status.tmp';p.write_text(json.dumps({'state':name,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),**kw},indent=2)+'\n');p.replace(ROOT/'status.json')
def publish(repo):
 import runpy,sys
 src=ROOT/'bolt-gpu1800limited-01';bench=src/'result/bench'
 assert json.loads((src/'result/outcome.json').read_text())['exit_code']==0
 assert (bench/'completed.json').exists()
 argv=sys.argv;sys.argv=['workload_energy.py','--events',str(bench/'events.jsonl'),'--sensors',str(src/'telemetry/sensors.jsonl'),'--out',str(src/'workload-summary.json')]
 try:runpy.run_path(str(repo/'scripts/workload_energy.py'))['main']()
 finally:sys.argv=argv
 work=json.loads((src/'workload-summary.json').read_text())['completed_workloads']
 assert len(work)==2 and all(x['workload']=='throughput' and x['profile']=='gpu1800_cpu60' and x['power_coverage_fraction']>=.99 and x['gpu_sample_stats']['clocks.sm']['max']<=1800 for x in work)
 shapes={}
 for phase in sorted(bench.glob('phase-*')):
  if not phase.is_dir():continue
  ack=json.loads((phase/'profile-ack.json').read_text());assert ack['cpu_ceiling_fraction']==.6 and ack['gpu_ceiling_mhz']==1800
  data=json.loads((phase/'throughput.json').read_text())['benchmarks'];assert len(data)==9
  for row in data:
   assert row['response_size']==128 and len(row['tg_throughput']['values'])==3
   values=shapes.setdefault((row['context_size'],row['concurrency']),{'decode':[],'prefill':[]})
   values['decode']+=row['tg_throughput']['values'];values['prefill']+=row['pp_throughput']['values']
 summary={'profile':'gpu1800_cpu60','paired_normal_comparison':False,'matrix_seconds_mean':statistics.mean(x['elapsed_s'] for x in work),'gpu_kj_mean':statistics.mean(x['gpu_reported_energy_j'] for x in work)/1000,'peak_acpi_c':max(x['max_acpi_c'] for x in work),'c1_decode':statistics.mean(shapes[(0,1)]['decode']),'c1_prefill':statistics.mean(shapes[(0,1)]['prefill']),'c4_decode_total':statistics.mean(shapes[(0,4)]['decode']),'job_id':(src/'job-id').read_text().strip()}
 (src/'followup-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 import re
 for p in src.rglob('*'):
  if p.is_file() and p.suffix in ['.json','.jsonl','.log','.md'] and re.search(r'hf_[A-Za-z0-9]{25,}|-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----',p.read_text(errors='replace')):raise RuntimeError('Credential-like content in '+str(p))
 env=os.environ.copy();env['GIT_SSH_COMMAND']='ssh -o BatchMode=yes -o IdentityAgent=none'
 subprocess.run(['git','fetch','origin'],cwd=repo,env=env,check=True)
 subprocess.run(['git','merge','--ff-only','origin/main'],cwd=repo,check=True)
 dest=repo/'experiments/bolt60-only-20261103';dest.mkdir(exist_ok=False)
 for name in ['spec.json','status.json','job-id','workload-summary.json','followup-summary.json','nvme-smart-before.json','nvme-smart-after.json']:shutil.copy2(src/name,dest/name)
 for name in ['followup.py','schedule.json','run.py','recover.py','switch-runtime.py']:shutil.copy2(ROOT/name,dest/name)
 with tarfile.open(dest/'raw-run.tar.gz','w:gz') as tf:tf.add(src,arcname=src.name)
 text='Bolt efficiency-only follow-up, Nov 3, 2026\nGPU1800MHz; CPU requested ceilings60% (P2340MHz/E1684.8MHz).\nTwo resident seeded throughput matrices, no repeat quality trial. No unrestricted retry.\nThe normal run in the earlier campaign stopped at90C; these are limited-only results, not a paired energy-saving estimate.\n'+json.dumps(summary,indent=2)+'\nGPU-reported energy is not wall energy. Stock automatic fans,90C guard and memory guards unchanged; original runtime/clocks restored before publishing.\n'
 (repo/'docs/BOLT60-ONLY-RESULTS-20261103.txt').write_text(text)
 note=f"""## Bolt at 60% — efficiency-only follow-up

The unrestricted comparison stopped at the 90°C guard. A separate two-pass test
used GPU **1,800 MHz** and CPU **60%** (performance cores **2,340 MHz**, efficiency
cores **1,684.8 MHz**). No unrestricted retry or repeat quality trial was run.

| c1 decode tok/s | c1 prefill tok/s | c4 decode total tok/s | Matrix seconds | GPU-reported kJ | Peak ACPI °C |
|---:|---:|---:|---:|---:|---:|
| {summary['c1_decode']:.1f} | {summary['c1_prefill']:,.0f} | {summary['c4_decode_total']:.1f} | {summary['matrix_seconds_mean']:.1f} | {summary['gpu_kj_mean']:.2f} | {summary['peak_acpi_c']:.1f} |

These are **unpaired limited-only results**; no normal-versus-efficiency energy
percentage can be calculated. [Report](docs/BOLT60-ONLY-RESULTS-20261103.txt) ·
[Raw evidence](experiments/bolt60-only-20261103/).

"""
 readme=repo/'README.md';old=readme.read_text();marker='## Findings from this campaign';assert marker in old;readme.write_text(old.replace(marker,note+marker,1))
 manifest={str(p.relative_to(dest)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.rglob('*') if p.is_file()};(dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 subprocess.run(['git','diff','--check'],cwd=repo,check=True)
 subprocess.run(['git','add','README.md','docs/BOLT60-ONLY-RESULTS-20261103.txt','experiments/bolt60-only-20261103'],cwd=repo,check=True)
 subprocess.run(['git','-c','user.name=Codex','-c','user.email=codex@openai.com','commit','-m','Publish Bolt efficiency-only follow-up without claiming a paired baseline'],cwd=repo,check=True)
 subprocess.run(['git','push','origin','HEAD:main'],cwd=repo,env=env,check=True)
 return summary
def main():
 cfg=json.loads((ROOT/'schedule.json').read_text());repo=Path(cfg['repo']);control=load('run');control.ROOT=ROOT;control.REPO=repo
 state('waiting_for_current_campaign',after=WAIT_FOR);deadline=time.monotonic()+43200
 while subprocess.check_output(['systemctl','show',WAIT_FOR,'--value','-p','ActiveState'],text=True).strip() in ['active','activating','deactivating']:
  if time.monotonic()>deadline:raise TimeoutError('Previous campaign still active after12h')
  time.sleep(10)
 previous=json.loads(Path('/home/d_wizard/local-ai/cap1800-20261103/status.json').read_text())
 if previous['state']!='complete_with_thermal_stop':raise RuntimeError('Previous campaign did not finish publication/cleanup; leaving Bolt unsubmitted')
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==cfg['source_commit']
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip()
 for path,sha in cfg['host_original_sha256'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha,path
 for name,sha in cfg['controller_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
 for tag,sha in cfg['images'].items():assert subprocess.check_output(['docker','image','inspect',tag,'--format','{{.Id}}'],text=True).strip()==sha,tag
 control.remote('mkdir -p ~/workspace/code/cap1800-plans')
 for name in ['model_campaign_job.py','paired_model_bench.py']:subprocess.run(control.SCP+[str(repo/'scripts'/name),control.HOST+':workspace/code/'],check=True)
 for name in ['bolt.json','qwen27.json']:subprocess.run(control.SCP+[str(repo/'configs/cap1800-20261103'/name),control.HOST+':workspace/code/cap1800-plans/'],check=True)
 state('running');(ROOT/'runtime-touched').write_text('owner-authorized Bolt CPU60-only follow-up\n')
 try:ok=control.model_run('bolt','01',limited_only=True)
 finally:load('recover').cleanup()
 if not ok:raise RuntimeError('Bolt limited-only run did not complete; retaining raw evidence')
 state('publishing');summary=publish(repo);state('complete',summary=summary)
 primary=Path('/home/d_wizard/local-ai/dgx_spark_serv')
 if not subprocess.check_output(['git','status','--porcelain'],cwd=primary,text=True).strip():subprocess.run(['git','pull','--ff-only'],cwd=primary,check=True)
 with Path('/home/d_wizard/local-ai/forum-watch/memory.txt').open('a') as f:f.write('\nBolt CPU60-only follow-up COMPLETE and published. Defaults restored. Status '+str(ROOT/'status.json')+'\n')
if __name__=='__main__':
 try:main()
 except BaseException as e:state('failed',error=repr(e));raise
