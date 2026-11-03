#!/usr/bin/env python3
"""Align paired benchmark events with host telemetry; GPU rail energy only."""
import argparse,json,math,re
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

def host_activity(first,last):
 def disks(row):
  return {p[2]:(int(p[5])*512,int(p[9])*512) for line in row.get('diskstats','').splitlines() for p in [line.split()] if len(p)>=14 and re.fullmatch(r'nvme\d+n\d+',p[2])}
 a,b=disks(first),disks(last)
 disk={k:{'read_bytes':b[k][0]-v[0],'written_bytes':b[k][1]-v[1]} for k,v in a.items() if k in b and all(y>=x for x,y in zip(v,b[k]))}
 def cpu(row):
  fields=row.get('proc_stat','').splitlines()[0].split()
  return [int(x) for x in fields[1:9]]
 x,y=cpu(first),cpu(last);delta=[v-u for u,v in zip(x,y)];total=sum(delta)
 return {'host_nvme_activity':disk,'host_cpu_busy_percent':100*sum(delta[i] for i in [0,1,2,5,6,7])/total if total>0 else None,'host_cpu_iowait_percent':100*delta[4]/total if total>0 else None,'host_vmstat_delta':{k:last.get('vmstat',{}).get(k,0)-v for k,v in first.get('vmstat',{}).items()}}

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
  activity=host_activity(selected[0],selected[-1]) if len(selected)>1 else {}
  results.append({**profile,'workload':event['label'],'exit_code':event['exit_code'],'elapsed_s':hi-lo,'gpu_reported_energy_j':energy if covered else None,'power_coverage_s':covered,'power_coverage_fraction':covered/(hi-lo) if hi>lo else None,'covered_mean_gpu_power_w':energy/covered if covered else None,'max_acpi_c':max(temps,default=None),'min_available_gib':min(available,default=None),'fan_rpm':{k:{'min':min(v),'max':max(v),'mean':sum(v)/len(v)} for k,v in fans.items()},**activity})
 output={'note':'GPU-reported rail energy only, not wall/system energy. Trapezoidal interpolation, excluding gaps >2.5s. Throughput energy includes harness warmups and context prefill. Partial workloads are not efficiency comparisons. CPU/NVMe/VM activity is host-wide and uses first/last samples inside workload, excluding boundary fractions; it is not per-job accounting. Swap counters count kernel pages.','completed_workloads':results,'unfinished_workloads':list(pending)}
 a.out.write_text(json.dumps(output,indent=2)+'\n')
if __name__=='__main__':main()
