#!/usr/bin/env python3
"""Prepare, queue and publish a guarded DeepSeek1017 256K comparison."""
import datetime,hashlib,importlib.util,json,os,re,runpy,shutil,statistics,subprocess,sys,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
LABEL='deepseek1017-gpu1800-01'
NAME='DeepSeek V4.1 Flash 1017 SAGE EXL3 1.62 bpw + DSpark5'
def load(name):
 s=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def state(name,**kw):
 row={'state':name,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),**kw};p=ROOT/'status.tmp';p.write_text(json.dumps(row,indent=2)+'\n');p.replace(ROOT/'status.json');print(json.dumps(row),flush=True)

def collect(repo,error):
 src=ROOT/LABEL;result=src/'result';bench=result/'bench'
 if not (src/'job-id').exists():raise RuntimeError('No GPU job submitted; inspect preparation/controller logs')
 outcome=json.loads((result/'outcome.json').read_text()) if (result/'outcome.json').exists() else None
 abort=json.loads((src/'watchdog/abort.json').read_text()) if (src/'watchdog/abort.json').exists() else None
 complete=bool(outcome and outcome['exit_code']==0 and (bench/'completed.json').exists())
 summary={'model':NAME,'complete':complete,'context_configured':262144,'actual_matrix_max_depth':8192,'server_max_num_seqs':1,'client_concurrency':[1,2,4],'job_id':(src/'job-id').read_text().strip(),'controller_error':error,'outcome':outcome,'abort':abort,'profiles':{},'matrix':[],'quality':None}
 if (bench/'events.jsonl').exists():
  argv=sys.argv;sys.argv=['workload_energy.py','--events',str(bench/'events.jsonl'),'--sensors',str(src/'telemetry/sensors.jsonl'),'--out',str(src/'workload-summary.json')]
  try:runpy.run_path(str(repo/'scripts/workload_energy.py'))['main']()
  finally:sys.argv=argv
  work=json.loads((src/'workload-summary.json').read_text())['completed_workloads']
  if complete:
   assert len(work)==5 and all(x['power_coverage_fraction']>=.99 for x in work)
   for prof in ['normal','gpu1800_cpu60']:
    runs=[x for x in work if x['workload']=='throughput' and x['profile']==prof];assert len(runs)==2
    if prof=='gpu1800_cpu60':assert all(x['gpu_sample_stats']['clocks.sm']['max']<=1800 for x in runs)
    summary['profiles'][prof]={'seconds_mean':statistics.mean(x['elapsed_s'] for x in runs),'gpu_kj_mean':statistics.mean(x['gpu_reported_energy_j'] for x in runs)/1000,'peak_acpi_c':max(x['max_acpi_c'] for x in runs),'nvme_read_gb_mean':statistics.mean(x['host_nvme_activity']['nvme0n1']['read_bytes'] for x in runs)/1e9,'nvme_write_gb_mean':statistics.mean(x['host_nvme_activity']['nvme0n1']['written_bytes'] for x in runs)/1e9}
  shapes={}
  for phase in bench.glob('phase-*'):
   if not phase.is_dir() or not (phase/'throughput.json').exists():continue
   ack=json.loads((phase/'profile-ack.json').read_text());prof=ack['profile']
   if prof=='gpu1800_cpu60':assert ack['gpu_ceiling_mhz']==1800 and ack['cpu_ceiling_fraction']==.6
   rows=json.loads((phase/'throughput.json').read_text())['benchmarks'];assert len(rows)==9
   for row in rows:
    assert row['response_size']==128 and len(row['tg_throughput']['values'])==3
    v=shapes.setdefault((prof,row['context_size'],row['concurrency']),{'decode':[],'prefill':[]});v['decode']+=row['tg_throughput']['values'];v['prefill']+=row['pp_throughput']['values']
  if complete:assert len(shapes)==18
  summary['matrix']=[{'profile':p,'depth':d,'concurrency':c,'decode_mean':statistics.mean(v['decode']),'prefill_mean':statistics.mean(v['prefill'])} for (p,d,c),v in shapes.items()]
 log=bench/'phase-1-normal/quality.log'
 if log.exists():
  text=log.read_text();score=re.search(r'Score:\s+(\d+) /',text);points=re.search(r'Points:\s+(\d+)/208',text);median=re.search(r'median turn: ([\d.]+)s',text)
  if score and points and median:summary['quality']={'score':int(score[1]),'points':int(points[1]),'median_turn_s':float(median[1])}
 if complete:assert summary['quality'] is not None
 (src/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');return summary

def publish(repo,summary):
 src=ROOT/LABEL
 for p in src.rglob('*'):
  if p.is_file() and p.suffix in ['.json','.jsonl','.log','.md'] and re.search(r'hf_[A-Za-z0-9]{25,}|-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----',p.read_text(errors='replace')):raise RuntimeError('Credential-like content in '+str(p))
 env=os.environ.copy();env['GIT_SSH_COMMAND']='ssh -o BatchMode=yes -o IdentityAgent=none'
 subprocess.run(['git','fetch','origin'],cwd=repo,env=env,check=True);subprocess.run(['git','merge','--ff-only','origin/main'],cwd=repo,check=True)
 dest=repo/'experiments/deepseek1017-20261103';dest.mkdir(exist_ok=False)
 for name in ['spec.json','job-id','status.json','summary.json','workload-summary.json','nvme-smart-before.json','nvme-smart-after.json']:
  if (src/name).exists():shutil.copy2(src/name,dest/name)
 for name in ['entry.py','run.py','recover.py','switch-runtime.py','schedule.json','download-pin.json','prepare-status.json','stage-status.json','image-pin.json']:
  if (ROOT/name).exists():shutil.copy2(ROOT/name,dest/name)
 for phase in (src/'result/bench').glob('phase-*') if (src/'result/bench').exists() else []:
  if phase.is_dir():
   for name in ['throughput.json','profile-ack.json']:
    if (phase/name).exists():shutil.copy2(phase/name,dest/(phase.name+'-'+name))
   for p in (phase/'quality').rglob('*.md') if (phase/'quality').exists() else []:shutil.copy2(p,dest/'quality.md')
 with tarfile.open(dest/'raw-run.tar.gz','w:gz') as tf:tf.add(src,arcname=src.name)
 (repo/'docs/DEEPSEEK1017-RESULTS-20261103.txt').write_text('DeepSeek V4.1 Flash1017 SAGE EXL3 1.62bpw,256K configured context\nNormal vsGPU1800MHz/CPU60,one normal-clock quality trial,ABBA throughput,20CPUquota. Default90C/2GiB hard/6GiB30s guards;stock fans. Server max-num-seqs1 per verified recipe: clients c2/c4 queue,not parallel engine execution. 256K configured is NOT a256K retrieval-quality result. Exact upstream command retained except paths,served-name and MAXLEN262144;serial compile workers1. No host VM/sysctl/swap/cache-drop changes. Runtime/clocks restored before publication. Read/write counters host-wide,GPUjoules not wallenergy.\n'+json.dumps(summary,indent=2)+'\n')
 p=repo/'README.md';text=p.read_text()
 if summary['complete']:
  q=summary['quality'];label='[DeepSeek V4.1 Flash 1017 SAGE EXL3 1.62 bpw + DSpark5](https://huggingface.co/vcruz305/DSV4.1-Flash-1017-SAGE-EXL3-1.62bpw)'
  marker='\nQuality differences in a single trial';assert marker in text
  text=text.replace(marker,f"| {label} | {q['score']} ({q['points']}/208) | {q['median_turn_s']:.1f}s |\n"+marker,1)
  rows=''
  for prof,title in [('normal','Normal‡'),('gpu1800_cpu60','60% GPU limit — 1,800 MHz; CPU 60%‡')]:
   c1=next(x for x in summary['matrix'] if x['profile']==prof and x['depth']==0 and x['concurrency']==1);c4=next(x for x in summary['matrix'] if x['profile']==prof and x['depth']==0 and x['concurrency']==4);s=summary['profiles'][prof]
   rows+=f"| {NAME} | {title} | {c1['decode_mean']:.1f} | {c1['prefill_mean']:,.0f} | {c4['decode_mean']:.1f} | {s['seconds_mean']:.1f} | {s['gpu_kj_mean']:.2f} | {s['peak_acpi_c']:.1f} |\n"
  marker='\n† **Bolt';assert marker in text;text=text.replace(marker,rows+'\n‡ DeepSeek uses **256K configured context** and **one active engine sequence**; c2/c4 clients queue. Its measured matrix reaches8K depth, not256K retrieval. [DeepSeek report](docs/DEEPSEEK1017-RESULTS-20261103.txt).\n'+marker,1)
  text=text.replace('DeepSeek V4.1 Flash 1017 SAGE EXL3 1.62 bpw at\n**256K configured context** remains a separate planned test, not measured here.','DeepSeek V4.1 Flash1017 at **256K configured context** is included in the tables; its different serving configuration is noted above.')
  text=text.replace('All use 20 CPU quota and 32K configured context.','All use 20 CPU quota; context is32K except DeepSeek’s256K.')
 else:
  note='**DeepSeek1017 attempt:** stopped before a complete comparison; see the [failure report](docs/DEEPSEEK1017-RESULTS-20261103.txt) and [raw evidence](experiments/deepseek1017-20261103/). No complete efficiency result is claimed.\n\n'
  text=text.replace('## Earlier results retained for reference',note+'## Earlier results retained for reference',1)
 p.write_text(text)
 (dest/'manifest.json').write_text(json.dumps({str(p.relative_to(dest)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.rglob('*') if p.is_file()},indent=2)+'\n')
 subprocess.run(['git','diff','--check'],cwd=repo,check=True);subprocess.run(['git','add','README.md','docs/DEEPSEEK1017-RESULTS-20261103.txt','experiments/deepseek1017-20261103'],cwd=repo,check=True)
 subprocess.run(['git','-c','user.name=Codex','-c','user.email=codex@openai.com','commit','-m','Publish DeepSeek1017 guarded256K experiment evidence'],cwd=repo,check=True);subprocess.run(['git','push','origin','HEAD:main'],cwd=repo,env=env,check=True)

def main():
 cfg=json.loads((ROOT/'schedule.json').read_text());repo=Path(cfg['repo']);deadline=time.monotonic()+43200;state('waiting_for_preparation')
 while True:
  prep=json.loads((ROOT/'prepare-status.json').read_text());stage=json.loads((ROOT/'stage-status.json').read_text())
  if prep['state']=='failed' or stage['state']=='failed':raise RuntimeError('Preparation/staging failed; inspect logs before submitting GPU work')
  if prep['state']=='ready' and stage['state']=='ready':break
  if time.monotonic()>deadline:raise TimeoutError('Preparation exceeded12h')
  time.sleep(10)
 state('building_benchmark_layer')
 build=Path('/home/d_wizard/local-ai/benchmark-tools/build')
 image_id=prep['image_id'];assert re.fullmatch('sha256:[a-f0-9]{64}',image_id)
 image_tag=prep['image'];assert re.fullmatch('[a-z0-9._/-]+:[a-zA-Z0-9._-]+',image_tag)
 assert subprocess.check_output(['docker','image','inspect',image_tag,'--format','{{.Id}}'],text=True).strip()==image_id
 (build/'Dockerfile.deepseek1017').write_text('FROM '+image_tag+'\nCOPY wheels /opt/benchmark-wheels\nRUN pip install --no-deps /opt/benchmark-wheels/*.whl && tool-eval-bench --help && python3 -m llama_benchy --help\n')
 subprocess.run(['docker','build','-f',str(build/'Dockerfile.deepseek1017'),'-t','deepseek1017-benchmarks:20261103',str(build)],check=True)
 (ROOT/'image-pin.json').write_text(subprocess.check_output(['docker','image','inspect','deepseek1017-benchmarks:20261103'],text=True))
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==cfg['source_commit']
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip()
 for p,sha in cfg['host_original_sha256'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha,p
 for name,sha in cfg['controller_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
 control=load('run');control.ROOT=ROOT;control.REPO=repo
 control.remote('mkdir -p ~/workspace/code/deepseek1017')
 for n in ['model_campaign_job.py','paired_model_bench.py']:subprocess.run(control.SCP+[str(repo/'scripts'/n),control.HOST+':workspace/code/'],check=True)
 for n in ['serve_inner.sh','serve-env.json']:subprocess.run(control.SCP+[str(repo/'configs/deepseek1017-20261103'/n),control.HOST+':workspace/code/deepseek1017/'],check=True)
 state('running');(ROOT/'runtime-touched').write_text('Owner-authorized DeepSeek1017 comparison\n');error=None
 try:control.model_run('deepseek1017','01')
 except Exception as e:error=repr(e)
 finally:load('recover').cleanup()
 summary=collect(repo,error);state('publishing',complete=summary['complete']);publish(repo,summary);state('complete' if summary['complete'] else 'stopped',summary=summary)
 primary=Path('/home/d_wizard/local-ai/dgx_spark_serv')
 if not subprocess.check_output(['git','status','--porcelain'],cwd=primary,text=True).strip():subprocess.run(['git','pull','--ff-only'],cwd=primary,env={**os.environ,'GIT_SSH_COMMAND':'ssh -o BatchMode=yes -o IdentityAgent=none'},check=True)
 with (Path('/home/d_wizard/local-ai/forum-watch/memory.txt')).open('a') as f:f.write('\nDeepSeek1017 campaign finished; see '+str(ROOT/'status.json')+' . Defaults restored and evidence published.\n')
if __name__=='__main__':
 try:main()
 except BaseException as e:state('failed',error=repr(e));raise
