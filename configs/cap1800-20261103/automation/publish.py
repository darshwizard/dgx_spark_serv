#!/usr/bin/env python3
"""Publish only a complete, validated four-model campaign. Preserve older runs."""
import csv,hashlib,json,re,shutil,statistics,subprocess,tarfile
from pathlib import Path
LIMIT='gpu1800_cpu80'
MODELS={'qwen27':('Qwen3.8-27B NVFP4 + DFlash2','nvidia/Qwen3.8-27B-NVFP4'),'bolt':('Nemotron 3.5 Bolt 74B-A9B 24GB + LiLiCorr','nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB'),'super':('Nemotron 3.5 Super VL 120B-A12B NVFP4 + LiLiCorr','nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4'),'flash':('Qwen3.8-Flash-Next FP4-Local + MTP4','nvidia/Qwen3.8-Flash-Next-FP4-Local')}
def render(summary,matrix):
 text='''# DGX Spark (GB10) — serving & benchmark findings

One NVIDIA DGX Spark, GB10, 121.7 GiB usable unified RAM. Latest complete campaign:
**November 3, 2026 — all four models, normal versus 60% GPU clock limit.**

## Model quality — measured at normal clocks

Quality measures task behavior, separately from the clock/energy comparison.
tool-eval-bench 3.0.1.dev9, hard mode, 104 scenarios, seed 42, thinking off;
one quality trial per model. Full reports retain task failures and safety
findings. These tests use text and mocked tools, not real-world tool actions.

| Exact model / setup | Quality /100 (points) | Median turn |
|---|---:|---:|
'''
 for model,(label,hf) in MODELS.items():
  q=summary[model]['quality'];text+=f"| [{label}](https://huggingface.co/{hf}) | {q['score']} ({q['points']}/208) | {q['median_turn_s']:.1f}s |\n"
 text+='''
Quality differences in a single trial are not an established universal ranking.
Model safety findings are in the full quality reports; they are not attributed
to the clock limit.

## Paired speed, energy and heat — all four models

**Normal:** default CPU/GPU clock limits. **60% GPU clock limit:** GPU ceiling
**1,800 MHz** (about 60% of the reported 3,003 MHz maximum), with CPU frequency
ceilings **80%** of their hardware maxima. CPU affinity stays unchanged. This is
a combined CPU/GPU clock profile, not a 60%-power setting or a GPU-only causal test.

**CPU speeds behind the profile labels** (requested frequency ceilings):

| CPU cores | Normal / default | CPU 80% profile | Reduction |
|---|---:|---:|---:|
| 10 Cortex-X925 performance cores | 3,900 MHz | 3,120 MHz | 780 MHz (20%) |
| 10 Cortex-A725 efficiency cores | 2,808 MHz | 2,246.4 MHz | 561.6 MHz (20%) |

Default permits operation up to these reported hardware maxima; it does not
mean a fixed clock at all times. Driver requests are distinct from independently
verified hardware clocks; the watchdog records hardware feedback for inspection.
The proposed performance-core-only **2,600 MHz** follow-up is **1,300 MHz / 33.3%**
below default, with efficiency cores unchanged. It is not this CPU 80% profile.

`c` means concurrent requests. **c1 decode** is output tokens/second for one
active request. **c4 decode total** is the combined rate for four simultaneous
requests (60 total is about 15 each if balanced). **Prefill** processes input
tokens before answer generation. The speed columns below use depth 0.

| Model / setup | Profile | c1 decode tok/s | c1 prefill tok/s | c4 decode total tok/s | Full matrix seconds | GPU-reported kJ | Matrix peak ACPI °C |
|---|---|---:|---:|---:|---:|---:|---:|
'''
 for model,(label,_) in MODELS.items():
  for prof,pname in [('normal','Normal'),(LIMIT,'60% GPU limit — 1,800 MHz; CPU 80%')]:
   a=next(r for r in matrix if r['model']==model and r['profile']==prof and r['depth']==0 and r['concurrency']==1);b=next(r for r in matrix if r['model']==model and r['profile']==prof and r['depth']==0 and r['concurrency']==4);s=summary[model]['profiles'][prof]
   text+=f"| {label} | {pname} | {a['decode_mean']:.1f} | {a['prefill_mean']:,.0f} | {b['decode_mean']:.1f} | {s['seconds_mean']:.1f} | {s['gpu_j_mean']/1000:.2f} | {s['peak_acpi_c']:.1f} |\n"
 text+='''
Seeded llama-benchy 0.4.1.dev1: pp2048, exactly 128 generated tokens in matrix
requests, depth 0/4096/8192, concurrency 1/2/4, three measured runs plus warmup
per shape. Two passes per profile, **Normal → 60% GPU limit → 60% GPU limit →
Normal**, keeping one server loaded. All use 20 CPU quota and 32K configured
context. Prefix cache resets verified before suites; cache/prompt details,
per-pass values and descriptive SD are in the report and raw data.

Energy/time cover the full matrix including warmups and harness probes, whose
small generation overhead can vary. They exclude clock transitions/cooldown.
GPU-reported energy is not whole-machine energy; CPU, NVMe, fans and PSU losses
are not fully accounted for. Different tokenizers also imply different text at
equal token counts. No wall meter or ambient-temperature sensor was available.

## Findings from this campaign

'''
 for model,(label,_) in MODELS.items():
  n=summary[model]['profiles']['normal'];c=summary[model]['profiles'][LIMIT]
  text+=f"- **{label}:** GPU-reported matrix energy changed **{100*(c['gpu_j_mean']/n['gpu_j_mean']-1):+.1f}%**, and elapsed time **{100*(c['seconds_mean']/n['seconds_mean']-1):+.1f}%**, under the 60% GPU limit / CPU 80% profile.\n"
 text+='''
Only two passes per profile on one host: these are measured observations, not
confidence intervals. Fans remained automatic; starting temperatures, fan speeds
and elapsed-run history matter. Check the fan/temperature timelines before
attributing a temperature difference to a particular component's power.

Flash Next retains the validated `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
startup mitigation. Previous memory-pressure stops and older results remain
archived. No firmware, EC or fan-control changes were made for this experiment.

**Full evidence:** [Campaign report](docs/CAP1800-RESULTS-20261103.txt) ·
[All matrix shapes/SD](experiments/cap1800-20261103/throughput-matrix.csv) ·
[Exact commands, quality reports and raw data](experiments/cap1800-20261103/) ·
[Serving recipes](docs/LARGE-MODEL-RECIPES-20261103.txt) ·
[Fan/cooling notes](hardware/FAN-OBSERVATIONS-20261102.txt).

Models were unloaded and default clock limits and the original queue runtime
restored before publication. DeepSeek V4.1 Flash 1017 SAGE EXL3 1.62 bpw at
**256K configured context** remains a separate planned test, not measured here.

## Earlier results retained for reference

[Earlier Super / Flash 2,402 MHz-limit campaign](docs/LARGE-MODEL-RESULTS-20261103.txt)
· [Earlier Qwen 27B / Bolt comparison](docs/QWEN-BOLT-COMPARISON-20261102.txt).
Those measurements used different clock settings and/or benchmark protocols;
the raw records are preserved rather than overwritten.
'''
 return text
def publish(root,repo):
 import runpy
 energy=runpy.run_path(str(repo/'scripts/workload_energy.py'))['main']
 summary={};matrix=[];dest=repo/'experiments/cap1800-20261103';dest.mkdir(exist_ok=False)
 for model in MODELS:
  src=root/(model+'-gpu1800-01');result=src/'result';assert json.loads((result/'outcome.json').read_text())['exit_code']==0
  assert (result/'bench/completed.json').exists()
  import sys
  old=sys.argv;sys.argv=['workload_energy.py','--events',str(result/'bench/events.jsonl'),'--sensors',str(src/'telemetry/sensors.jsonl'),'--out',str(src/'workload-summary.json')]
  try:energy()
  finally:sys.argv=old
  for p in src.rglob('*'):
   if p.is_file() and p.suffix in ['.json','.jsonl','.log','.md'] and re.search(r'hf_[A-Za-z0-9]{25,}|-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----',p.read_text(errors='replace')):raise RuntimeError('Credential-like content: '+str(p))
  work=json.loads((src/'workload-summary.json').read_text())['completed_workloads'];assert len(work)==5
  log=(result/'bench/phase-1-normal/quality.log').read_text()
  q={'score':int(re.search(r'Score:\s+(\d+) /',log)[1]),'points':int(re.search(r'Points:\s+(\d+)/208',log)[1]),'median_turn_s':float(re.search(r'median turn: ([\d.]+)s',log)[1])}
  groups={}
  out=dest/model;out.mkdir()
  for phase in sorted((result/'bench').glob('phase-*')):
   if not phase.is_dir():continue
   prof='normal' if phase.name.endswith('-normal') else LIMIT
   ack=json.loads((phase/'profile-ack.json').read_text());assert ack['profile']==prof
   data=json.loads((phase/'throughput.json').read_text());assert len(data['benchmarks'])==9
   for r in data['benchmarks']:
    assert r['response_size']==128 and len(r['tg_throughput']['values'])==3
    g=groups.setdefault((r['context_size'],r['concurrency'],prof),{'pp':[],'tg':[]});g['pp']+=r['pp_throughput']['values'];g['tg']+=r['tg_throughput']['values']
   shutil.copy2(phase/'throughput.json',out/(phase.name+'-throughput.json'));shutil.copy2(phase/'profile-ack.json',out/(phase.name+'-profile.json'))
  for (depth,c,prof),g in sorted(groups.items()):matrix.append({'model':model,'depth':depth,'concurrency':c,'profile':prof,'prefill_mean':statistics.mean(g['pp']),'decode_mean':statistics.mean(g['tg']),'decode_sd':statistics.pstdev(g['tg'])})
  profiles={}
  for prof in ['normal',LIMIT]:
   w=[x for x in work if x['profile']==prof and x['workload']=='throughput'];assert len(w)==2
   assert all(x['power_coverage_fraction']>=.99 for x in w)
   if prof==LIMIT:assert all(x['gpu_sample_stats']['clocks.sm']['max']<=1800 for x in w)
   profiles[prof]={'seconds_mean':statistics.mean(x['elapsed_s'] for x in w),'gpu_j_mean':statistics.mean(x['gpu_reported_energy_j'] for x in w),'peak_acpi_c':max(x['max_acpi_c'] for x in w),'nvme_read_gb_mean':statistics.mean(sum(v['read_bytes'] for v in x['host_nvme_activity'].values())/1e9 for x in w)}
  summary[model]={'quality':q,'profiles':profiles,'job_id':(src/'job-id').read_text()}
  for name in ['spec.json','status.json','job-id','workload-summary.json']:shutil.copy2(src/name,out/name)
  shutil.copy2(result/'launch.json',out/'launch.json');shutil.copy2(next((result/'bench/phase-1-normal/quality').rglob('*.md')),out/'quality.md')
  shutil.copy2(src/'telemetry/summary.json',out/'telemetry-summary.json')
  with tarfile.open(out/'raw-run.tar.gz','w:gz') as tf:tf.add(src,arcname=src.name)
 with (dest/'throughput-matrix.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(matrix[0]));w.writeheader();w.writerows(matrix)
 (dest/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 for name in ['schedule.json','run.py','switch-runtime.py','publish.py','entry.py','recover.py']:shutil.copy2(root/name,dest/name)
 old=(repo/'README.md').read_text();history=old[old.index('\n---\n'):];(repo/'README.md').write_text(render(summary,matrix)+history)
 report='Completed four-model campaign: normal vs GPU 1800 MHz (about 60% hardware maximum), CPU ceilings80%.\nOne normal-clock quality trial per model; quality warnings are behavioral findings in each quality report, not power effects.\nFull model/profile means and measurements:\n'+json.dumps(summary,indent=2)+'\nRaw data, per-pass JSON, quality Markdown and exact configs: ../experiments/cap1800-20261103/\n20CPU quota,118GiB charged RAM,16GiB shm;90C hottest-zone stop;2GiB hard/6GiB30s soft memory floors. No fan/firmware/EC change. GPU-reported energy is not wall/system energy. Two matrices/profile; descriptive results on one host. All models unloaded/settings restored before publication.\n'
 (repo/'docs/CAP1800-RESULTS-20261103.txt').write_text(report)
 files={str(p.relative_to(dest)):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in dest.rglob('*') if p.is_file()};(dest/'manifest.json').write_text(json.dumps(files,indent=2)+'\n')
 subprocess.run(['git','diff','--check'],cwd=repo,check=True)
 subprocess.run(['git','add','README.md','docs/CAP1800-RESULTS-20261103.txt','experiments/cap1800-20261103'],cwd=repo,check=True)
 subprocess.run(['git','-c','user.name=Codex','-c','user.email=codex@openai.com','commit','-m','Replace headline comparison with completed 1800 MHz four-model reruns'],cwd=repo,check=True)
 subprocess.run(['git','fetch','origin'],cwd=repo,check=True);subprocess.run(['git','-c','user.name=Codex','-c','user.email=codex@openai.com','rebase','origin/main'],cwd=repo,check=True)
 import os
 env=os.environ.copy();env['GIT_SSH_COMMAND']='ssh -o BatchMode=yes -o IdentityAgent=none'
 subprocess.run(['git','push','origin','HEAD:main'],cwd=repo,env=env,check=True)
 return summary
