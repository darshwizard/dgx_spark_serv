#!/usr/bin/env python3
"""Synthetic DeepSeek collection/publication, including queued-concurrency caveat."""
import json,runpy,tempfile
from pathlib import Path
from unittest.mock import patch
source=Path(__file__).resolve().parents[1]
ns=runpy.run_path(str(source/'configs/deepseek1017-20261103/entry.py'))
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'run';repo=Path(tmp)/'repo';root.mkdir();repo.mkdir();ns['collect'].__globals__['ROOT']=root
 for name in ['scripts','docs','experiments']:(repo/name).mkdir()
 (repo/'scripts/workload_energy.py').write_bytes((source/'scripts/workload_energy.py').read_bytes())
 (repo/'README.md').write_bytes((source/'README.md').read_bytes())
 for name in ['entry.py','run.py','recover.py','switch-runtime.py','schedule.json']:(root/name).write_text('{}')
 src=root/'deepseek1017-gpu1800-01';bench=src/'result/bench';bench.mkdir(parents=True);(src/'telemetry').mkdir()
 for name in ['spec.json','status.json','nvme-smart-before.json','nvme-smart-after.json']:(src/name).write_text('{}')
 (src/'job-id').write_text('0'*32);(src/'result/outcome.json').write_text('{"exit_code":0}');(bench/'completed.json').write_text('{}')
 events=[]
 for seq,prof in enumerate(['normal','gpu1800_cpu60','gpu1800_cpu60','normal'],1):
  folder=bench/f'phase-{seq}-{prof}';folder.mkdir()
  (folder/'profile-ack.json').write_text(json.dumps({'profile':prof,'cpu_ceiling_fraction':.6 if prof!='normal' else 1,'gpu_ceiling_mhz':1800 if prof!='normal' else None}))
  (folder/'throughput.json').write_text(json.dumps({'benchmarks':[{'context_size':d,'concurrency':c,'response_size':128,'tg_throughput':{'values':[20]*3},'pp_throughput':{'values':[100]*3}} for d in [0,4096,8192] for c in [1,2,4]]}))
  events.append({'event':'profile_ready','seq':seq,'profile':prof})
  if seq==1:
   (folder/'quality.log').write_text('Score: 88 / 100 Points: 184/208 median turn: 2.2s')
   events.extend([{'event':'workload_start','label':'quality','monotonic_s':1},{'event':'workload_end','label':'quality','monotonic_s':3,'exit_code':0}])
  events.extend([{'event':'workload_start','label':'throughput','monotonic_s':seq*10+1},{'event':'workload_end','label':'throughput','monotonic_s':seq*10+9,'exit_code':0}])
 (bench/'events.jsonl').write_text('\n'.join(json.dumps(x) for x in events)+'\n')
 rows=[{'monotonic_s':t,'gpus':[{'power.draw':20,'clocks.sm':1794,'utilization.gpu':90}],'thermal_zones':[{'celsius':60}]*7,'meminfo_kib':{'MemAvailable':10*1048576},'hwmon':[],'proc_stat':f'cpu {t} 0 {t} {10*t} 0 0 0 0','diskstats':f'259 0 nvme0n1 1 2 {t} 4 5 6 {t} 8 9 10 11','vmstat':{'oom_kill':0}} for t in range(51)]
 (src/'telemetry/sensors.jsonl').write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
 summary=ns['collect'](repo,None);assert summary['complete'] and len(summary['matrix'])==18 and summary['server_max_num_seqs']==1
 calls=[]
 with patch('subprocess.run',lambda cmd,**kw:calls.append(cmd)):ns['publish'](repo,summary)
 text=(repo/'README.md').read_text();assert 'one active engine sequence' in text and '256K configured context' in text
 assert '\n\n| [DeepSeek' not in text and '\n\n| DeepSeek' not in text
 assert text.count('| DeepSeek V4.1 Flash 1017 SAGE EXL3 1.62 bpw + DSpark5 |')==2
 assert (repo/'experiments/deepseek1017-20261103/manifest.json').exists()
 print('PASS: DeepSeek ABBA results validated, tables remain contiguous, queued-concurrency caveat retained; no GPU/Git/network')
