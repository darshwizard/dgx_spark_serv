#!/usr/bin/env python3
"""Align paired benchmark events with host telemetry; GPU rail energy only."""
import argparse,json,math
from pathlib import Path

def integrate(rows,start,end,max_gap=2.5):
 energy=covered=0.0
 for a,b in zip(rows,rows[1:]):
  x,y=a['monotonic_s'],b['monotonic_s'];lo,hi=max(start,x),min(end,y)
  if hi<=lo or y<=x or y-x>max_gap:continue
  if len(a.get('gpus',[]))!=1 or len(b.get('gpus',[]))!=1:continue
  p,q=a['gpus'][0].get('power.draw'),b['gpus'][0].get('power.draw')
  if not all(isinstance(v,(int,float)) and math.isfinite(v) and v>=0 for v in [p,q]):continue
  u=p+(q-p)*(lo-x)/(y-x);v=p+(q-p)*(hi-x)/(y-x)
  energy+=(u+v)/2*(hi-lo);covered+=hi-lo
 return energy,covered

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--events',type=Path,required=True);p.add_argument('--sensors',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 rows=[json.loads(x) for x in a.sensors.read_text().splitlines() if x.strip()]
 rows.sort(key=lambda x:x['monotonic_s'])
 phase=None;pending={};results=[]
 for line in a.events.read_text().splitlines():
  event=json.loads(line);name=event['event']
  if name=='profile_ready':phase={k:event[k] for k in ['seq','profile']}
  if name=='workload_start':pending[event['label']]=(event,phase)
  if name!='workload_end':continue
  start,profile=pending.pop(event['label']);lo,hi=start['monotonic_s'],event['monotonic_s']
  energy,covered=integrate(rows,lo,hi);selected=[r for r in rows if lo<=r['monotonic_s']<=hi]
  temps=[z['celsius'] for r in selected for z in r.get('thermal_zones',[]) if z.get('celsius') is not None]
  fans={}
  for r in selected:
   for h in r.get('hwmon',[]):
    for k,v in h.get('sensors',{}).items():
     if k.startswith('fan') and v.get('raw') is not None:fans.setdefault(h['id']+'/'+k,[]).append(v['raw'])
  available=[r['meminfo_kib']['MemAvailable']/1048576 for r in selected if 'MemAvailable' in r.get('meminfo_kib',{})]
  results.append({**profile,'workload':event['label'],'exit_code':event['exit_code'],'elapsed_s':hi-lo,'gpu_reported_energy_j':energy if covered else None,'power_coverage_s':covered,'power_coverage_fraction':covered/(hi-lo) if hi>lo else None,'covered_mean_gpu_power_w':energy/covered if covered else None,'max_acpi_c':max(temps,default=None),'min_available_gib':min(available,default=None),'fan_rpm':{k:{'min':min(v),'max':max(v),'mean':sum(v)/len(v)} for k,v in fans.items()}})
 output={'note':'GPU-reported rail energy only, not wall/system energy. Trapezoidal interpolation, excluding gaps >2.5s. Throughput energy includes harness warmups and context prefill. Partial workloads are not efficiency comparisons.','completed_workloads':results,'unfinished_workloads':list(pending)}
 a.out.write_text(json.dumps(output,indent=2)+'\n')
if __name__=='__main__':main()
