#!/usr/bin/env python3
"""Summarize completed Bolt pilot artifacts, excluding startup from timed energy.

Usage: python3 scripts/summarize_bolt.py ARTIFACT_DIRECTORY
Directory contains bolt-RECIPE-PROFILE-01 and matching -telemetry directories.
"""
import argparse,json,statistics
from pathlib import Path

def lines(path):return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]
def median(values):return statistics.median(values) if values else None

def summarize(root):
 out=[]
 for run in sorted(root.glob('bolt-*-01')):
  bench=run/'bench';telemetry=root/(run.name+'-telemetry')/'sensors.jsonl'
  if not (bench/'summary.json').exists() or not telemetry.exists():continue
  requests=lines(bench/'requests.jsonl');timed=[r for r in requests if not r['label'].startswith('smoke-')]
  if not timed:continue
  start=min(r['monotonic_start'] for r in timed);end=max(r['monotonic_end'] for r in timed)
  all_samples=lines(telemetry);samples=[s for s in all_samples if start<=s['monotonic_s']<=end]
  energy=covered=0.
  # Clip linear interpolation to the benchmark interval, omit gaps >2.5s.
  for a,b in zip(all_samples,all_samples[1:]):
   t0,t1=a['monotonic_s'],b['monotonic_s'];dt=t1-t0
   lo,hi=max(t0,start),min(t1,end)
   p0=(a.get('gpus') or [{}])[0].get('power.draw');p1=(b.get('gpus') or [{}])[0].get('power.draw')
   if hi<=lo or not 0<dt<=2.5 or not all(isinstance(x,(int,float)) for x in [p0,p1]):continue
   v0=p0+(p1-p0)*(lo-t0)/dt;v1=p0+(p1-p0)*(hi-t0)/dt
   energy+=(v0+v1)/2*(hi-lo);covered+=hi-lo
  batches=lines(bench/'batches.jsonl');quality=lines(bench/'quality.jsonl')
  temperatures=[z['celsius'] for s in samples for z in s['thermal_zones'] if z.get('celsius') is not None]
  gpu=[g for s in samples for g in s.get('gpus',[])]
  tokens=sum((r.get('usage') or {}).get('completion_tokens',0) for r in timed)
  entry={'run':run.name,'launch':json.loads((run/'launch.json').read_text()),
   'requests':len(requests),'request_errors':sum(r['error'] is not None for r in requests),
   'gates':json.loads((bench/'gates.json').read_text()),'retrieval_correct':sum(x['correct'] for x in quality),'retrieval_total':len(quality),
   'timed_interval_s':end-start,'timed_output_tokens':tokens,'timed_gpu_reported_energy_j':energy,'energy_coverage_s':covered,
   'gpu_reported_j_per_output_token':energy/tokens if tokens else None,
   'timed_peak_sensor_c':max(temperatures,default=None),
   'timed_gpu_sm_mhz_median':median([g['clocks.sm'] for g in gpu if isinstance(g.get('clocks.sm'),(int,float))]),
   'timed_gpu_sm_mhz_max':max([g['clocks.sm'] for g in gpu if isinstance(g.get('clocks.sm'),(int,float))],default=None),
   'timed_gpu_power_w_mean':statistics.mean([g['power.draw'] for g in gpu if isinstance(g.get('power.draw'),(int,float))]) if gpu else None,
   'thermal_slowdown_samples':sum(any(g.get(k)=='Active' for k in ['clocks_event_reasons.sw_thermal_slowdown','clocks_event_reasons.hw_thermal_slowdown']) for g in gpu),
   'truncated_throughput_requests':sum(r['finish_reason']=='length' for r in timed if not r['label'].startswith('long-')),
   'batches':[]}
  for name in ['prose','code','structured']:
   for c in [1,2,4]:
    rows=[b for b in batches if b['workload']==name and b['concurrency']==c]
    entry['batches'].append({'workload':name,'concurrency':c,'n':len(rows),'median_aggregate_output_tokens_per_wall_s':median([b['aggregate_tokens_per_wall_s'] for b in rows])})
  out.append(entry)
 return {'note':'Fixed 256-token throughput workloads generally truncate; not completed-task quality. Retrieval and smoke gates are narrow checks. Energy is GPU-reported only, excludes startup, includes prefill and inter-request gaps; no wall/system efficiency claim. Sequential pilot, not randomized paired thermal trials.','runs':out}

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);a=p.parse_args()
 print(json.dumps(summarize(a.root),indent=2))
