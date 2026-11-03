#!/usr/bin/env python3
"""Recover only this campaign's jobs and controls; refuse foreign active jobs."""
import json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def cleanup():
 cfg=json.loads((ROOT/'schedule.json').read_text());repo=Path(cfg['repo'])
 if not (ROOT/'runtime-touched').exists():return
 ssh=['ssh','-i','/home/d_wizard/.ssh/id_ed25519_compute_bench','-o','IdentitiesOnly=yes','-o','BatchMode=yes','agent-bench@192.168.1.240']
 rows=json.loads(subprocess.check_output(ssh+['compute-job status'],text=True))['result']
 own=[]
 for p in ROOT.glob('*/job-id'):
  jid=p.read_text().strip()
  if not re.fullmatch('[a-f0-9]{32}',jid):raise RuntimeError('Malformed recorded job ID')
  own.append(jid)
 for row in rows:
  if row['id'] in own and row['state'] in ['running','queued']:subprocess.run(ssh+['compute-job cancel '+row['id']],check=True)
 check="import json,sqlite3; d=sqlite3.connect('file:/var/lib/compute-queue/jobs.db?mode=ro',uri=True); print(json.dumps(d.execute(\"select id from jobs where state in ('running','queued')\").fetchall()))"
 active=json.loads(subprocess.check_output(['sudo','-n','python3','-c',check],text=True))
 if active:raise RuntimeError('Queue has other active jobs; refusing global clock/runtime restoration')
 for p in ROOT.glob('*/phase-*-clocks.json'):
  subprocess.run(['sudo','-n','python3',str(repo/'scripts/clock_profile.py'),'restore','--state',str(p)],check=True,stdout=subprocess.DEVNULL)
 subprocess.run(['sudo','-n','python3',str(ROOT/'switch-runtime.py'),'restore'],check=True)
 (ROOT/'restored.json').write_text(json.dumps({'restored':True,'jobs':own})+'\n')
if __name__=='__main__':cleanup()
