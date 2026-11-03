#!/usr/bin/env python3
"""Synthetic limited-only collection: no GPU, Git mutation or network calls."""
import json,runpy,tempfile
from pathlib import Path
from unittest.mock import patch
source=Path(__file__).resolve().parents[1]
ns=runpy.run_path(str(source/'configs/bolt60-only-20261103/followup.py'))
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'run';repo=Path(tmp)/'repo';root.mkdir();repo.mkdir()
 ns['publish'].__globals__['ROOT']=root
 for name in ['scripts','docs','experiments']:(repo/name).mkdir()
 (repo/'scripts/workload_energy.py').write_bytes((source/'scripts/workload_energy.py').read_bytes())
 (repo/'README.md').write_text('Bolt normal run stopped at90C.\n## Findings from this campaign\nExisting findings\n')
 for name in ['followup.py','schedule.json','run.py','recover.py','switch-runtime.py']:(root/name).write_text('{}')
 src=root/'bolt-gpu1800limited-01';bench=src/'result/bench';bench.mkdir(parents=True);(src/'telemetry').mkdir()
 for name in ['spec.json','status.json','nvme-smart-before.json','nvme-smart-after.json']:(src/name).write_text('{}')
 (src/'job-id').write_text('0'*32);(src/'result/outcome.json').write_text('{"exit_code":0}');(bench/'completed.json').write_text('{}')
 events=[]
 for seq in [1,2]:
  folder=bench/f'phase-{seq}-gpu1800_cpu60';folder.mkdir()
  (folder/'profile-ack.json').write_text('{"cpu_ceiling_fraction":0.6,"gpu_ceiling_mhz":1800}')
  (folder/'throughput.json').write_text(json.dumps({'benchmarks':[{'context_size':d,'concurrency':c,'response_size':128,'tg_throughput':{'values':[20,20,20]},'pp_throughput':{'values':[100,100,100]}} for d in [0,4096,8192] for c in [1,2,4]]}))
  events.extend([{'event':'profile_ready','seq':seq,'profile':'gpu1800_cpu60'},{'event':'workload_start','label':'throughput','monotonic_s':seq*10+1},{'event':'workload_end','label':'throughput','monotonic_s':seq*10+9,'exit_code':0}])
 (bench/'events.jsonl').write_text('\n'.join(json.dumps(x) for x in events)+'\n')
 rows=[{'monotonic_s':t,'gpus':[{'power.draw':20,'clocks.sm':1794,'utilization.gpu':90}],'thermal_zones':[{'celsius':60}]*7,'meminfo_kib':{'MemAvailable':10*1048576},'hwmon':[],'proc_stat':f'cpu {t} 0 {t} {10*t} 0 0 0 0','diskstats':f'259 0 nvme0n1 1 2 {t} 4 5 6 {t} 8 9 10 11','vmstat':{'oom_kill':0}} for t in range(31)]
 (src/'telemetry/sensors.jsonl').write_text('\n'.join(json.dumps(x) for x in rows)+'\n')
 calls=[]
 with patch('subprocess.run',lambda cmd,**kw:calls.append(cmd)):
  summary=ns['publish'](repo)
 assert summary['paired_normal_comparison'] is False and summary['c1_decode']==20
 text=(repo/'README.md').read_text();assert 'unpaired limited-only' in text and 'Existing findings' in text
 assert (repo/'experiments/bolt60-only-20261103/manifest.json').exists()
 assert any(x[-2:]==['origin','HEAD:main'] for x in calls)
 print('PASS: two limited-only passes archived/published without inventing a normal baseline; Git/network mocked')
