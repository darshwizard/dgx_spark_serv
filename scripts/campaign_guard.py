#!/usr/bin/env python3
"""Owner-run watchdog outside job cgroup. Only cancels its agent-bench queue job."""
import argparse,json,os,pwd,signal,sqlite3,subprocess,time
from pathlib import Path

def decision(available_bytes,temperatures):
 if available_bytes is None or len(temperatures)!=7:return 'required_sensor_missing'
 if available_bytes<2*1024**3:return 'host_available_below_2GiB'
 if max(temperatures)>=90:return 'thermal_limit_90C'
 return None

def main():
 p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--parent',type=int,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 if os.geteuid()!=0:raise SystemExit('Owner/root required')
 if len(a.job)!=32 or any(c not in '0123456789abcdef' for c in a.job):raise SystemExit('Invalid queue job ID')
 uid=pwd.getpwnam('agent-bench').pw_uid
 def job():
  with sqlite3.connect('file:/var/lib/compute-queue/jobs.db?mode=ro',uri=True) as db:
   row=db.execute('select uid,state from jobs where id=?',(a.job,)).fetchone()
  if not row or row[0]!=uid:raise RuntimeError('Not our benchmark job')
  return row[1]
 def cancel(reason):
  r=subprocess.run(['runuser','-u','agent-bench','--','compute-job','cancel',a.job],capture_output=True,text=True,timeout=20)
  (a.out/'abort.json').write_text(json.dumps({'reason':reason,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'unix_s':time.time()},indent=2))
 job();a.out.mkdir(parents=True,exist_ok=False);a.out.chmod(0o755)
 def stop(*_):
  if job() in ['queued','running']:cancel('watchdog_terminated')
  raise SystemExit(1)
 signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
 (a.out/'armed').write_text(a.job)
 baseline_mem={x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines()}
 swap_baseline=baseline_mem['SwapTotal']-baseline_mem['SwapFree']
 try:
  with (a.out/'health.jsonl').open('w',buffering=1) as f:
   tick=0
   while True:
    if tick%10==0 and job() not in ['queued','running']:return
    try:os.kill(a.parent,0)
    except ProcessLookupError:cancel('controller_missing');return
    mem={x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines()}
    temps=[float(x.read_text())/1000 for x in Path('/sys/class/thermal').glob('thermal_zone*/temp')]
    reason=decision(mem.get('MemAvailable'),temps)
    if mem['SwapTotal']-mem['SwapFree']-swap_baseline>64*1024**2:reason='host_swap_growth_above_64MiB'
    if tick%10==0 or reason:
     f.write(json.dumps({'unix_s':time.time(),'monotonic_s':time.monotonic(),'mem_available_bytes':mem.get('MemAvailable'),'hottest_c':max(temps,default=None),'swap_used_bytes':mem['SwapTotal']-mem['SwapFree'],'reason':reason})+'\n')
    if reason:cancel(reason);return
    tick+=1;time.sleep(.1)
 except BaseException:
  if job() in ['queued','running']:cancel('watchdog_exception')
  raise
if __name__=='__main__':main()
