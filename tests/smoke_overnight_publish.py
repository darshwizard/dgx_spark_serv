#!/usr/bin/env python3
"""Synthetic end-to-end collection/publication test; no GPU, Git or network calls."""
import json,runpy,tempfile
from pathlib import Path
from unittest.mock import patch
source=Path(__file__).resolve().parents[1]
ns=runpy.run_path(str(source/'configs/cap1800-20261103/automation/publish.py'))
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'runs';repo=Path(tmp)/'repo';root.mkdir();repo.mkdir();(repo/'scripts').mkdir();(repo/'docs').mkdir();(repo/'experiments').mkdir()
 (repo/'scripts/workload_energy.py').write_bytes((source/'scripts/workload_energy.py').read_bytes())
 (repo/'README.md').write_text('Prior results\n---\nHistorical material\n')
 for name in ['schedule.json','run.py','switch-runtime.py','publish.py','entry.py','recover.py']:(root/name).write_text('{}\n')
 for model in ns['MODELS']:
  run=root/(model+'-gpu1800-01');bench=run/'result/bench';bench.mkdir(parents=True);telemetry=run/'telemetry';telemetry.mkdir()
  for p in ['spec.json','status.json','result/launch.json','nvme-smart-before.json','nvme-smart-after.json']: (run/p).write_text('{}')
  (run/'job-id').write_text('0'*32);(run/'result/outcome.json').write_text('{"exit_code":0}');(bench/'completed.json').write_text('{}');(telemetry/'summary.json').write_text('{}')
  events=[]
  for seq,prof in enumerate(['normal','gpu1800_cpu60','gpu1800_cpu60','normal'],1):
   phase=bench/f'phase-{seq}-{prof}';phase.mkdir();(phase/'profile-ack.json').write_text(json.dumps({'profile':prof,'gpu_ceiling_mhz':1800 if prof!='normal' else None,'cpu_ceiling_fraction':0.6 if prof!='normal' else 1.0}))
   data={'benchmarks':[{'context_size':d,'concurrency':c,'response_size':128,'pp_throughput':{'values':[100,100,100]},'tg_throughput':{'values':[20,20,20]}} for d in [0,4096,8192] for c in [1,2,4]]};(phase/'throughput.json').write_text(json.dumps(data))
   events.append({'event':'profile_ready','seq':seq,'profile':prof})
   windows=[('quality',1,9),('throughput',11,19)] if seq==1 else [('throughput',10*seq+1,10*seq+9)]
   if seq==1:
    (phase/'quality.log').write_text('Score: 90 / 100\nPoints: 187/208\nmedian turn: 1.9s\n');(phase/'quality').mkdir();(phase/'quality/report.md').write_text('Synthetic fixture only')
   for label,a,b in windows:events.extend([{'event':'workload_start','label':label,'monotonic_s':a},{'event':'workload_end','label':label,'monotonic_s':b,'exit_code':0}])
  (bench/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events)+'\n')
  rows=[{'monotonic_s':t,'gpus':[{'power.draw':20,'clocks.sm':1790 if 20<=t<=40 else 2398,'utilization.gpu':90}],'thermal_zones':[{'celsius':60}]*7,'meminfo_kib':{'MemAvailable':10*1048576},'hwmon':[],'proc_stat':f'cpu {t} 0 {t} {10*t} 0 0 0 0','diskstats':f'259 0 nvme0n1 1 2 {t} 4 5 6 {t} 8 9 10 11','vmstat':{'oom_kill':0}} for t in range(51)]
  (telemetry/'sensors.jsonl').write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
 calls=[]
 with patch('subprocess.run',lambda cmd,**kw:calls.append(cmd)):
  summary=ns['publish'](root,repo)
 assert len(summary)==4 and (repo/'experiments/cap1800-20261103/manifest.json').exists()
 text=(repo/'README.md').read_text();assert '1,800 MHz' in text and 'Historical material' in text and 'CPU 60%' in text
 assert any(c[-2:]==['origin','HEAD:main'] for c in calls)
 assert not any('force' in str(c) for c in calls)
 print('PASS: all four synthetic runs collected, 1800 MHz validation, tables/archives/manifest generated; Git/network mocked')
