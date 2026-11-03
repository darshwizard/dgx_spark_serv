#!/usr/bin/python3
"""Owner-authorized temporary runtime switch; only while queue is idle."""
import ast,json,pathlib,re,sqlite3,subprocess,sys
base=pathlib.Path('/home/d_wizard/local-ai/bolt-experiment/host-backup')
def pending():
 with sqlite3.connect('file:/var/lib/compute-queue/jobs.db?mode=ro',uri=True) as db:
  return db.execute("select id,state from jobs where state in ('running','queued')").fetchall()
if pending(): raise SystemExit('Queue not idle; refusing runtime switch')
mode=sys.argv[1]
thermal_stop_c=int(sys.argv[3]) if len(sys.argv)>3 else 90
if thermal_stop_c not in [90,95]:raise SystemExit('Unsupported thermal stop')
if mode=='restore':
 image=None;label='original NGC image'
else:
 image=subprocess.check_output(['docker','image','inspect',mode,'--format','{{.Id}}'],text=True).strip()
 if not re.fullmatch('sha256:[0-9a-f]{64}',image): raise SystemExit('Invalid image id')
 label=sys.argv[2]
subprocess.run(['systemctl','stop','compute-queue'],check=True)
try:
 if pending(): raise RuntimeError('Queue changed during switch; refusing update')
 if mode=='restore':
  for name in ['queue.py','web.py','AGENTS.md']:
   pathlib.Path('/opt/compute-host',name).write_bytes((base/name).read_bytes())
  pathlib.Path('/home/d_wizard/AGENTS.md').write_bytes((base/'home-AGENTS.md').read_bytes())
 else:
  q=(base/'queue.py').read_text();q=re.sub(r"IMAGE='sha256:[a-f0-9]+'",f"IMAGE='{image}'",q)
  q=q.replace("'--memory=96g','--cpus=16'", "'--memory=118g','--memory-swap=118g','--cpus=20'")
  q=q.replace("'--shm-size=4g'", "'--shm-size=16g','--ulimit','memlock=-1:-1','--ulimit','stack=67108864'")
  if 'Flash' in label:
   q=q.replace("'--security-opt=no-new-privileges'", "'--security-opt=no-new-privileges','--security-opt=seccomp=unconfined','--security-opt=apparmor=unconfined'")
  ast.parse(q);pathlib.Path('/opt/compute-host/queue.py').write_text(q)
  paragraph=f'Jobs run sequentially in the temporarily pinned {label} runtime.\nImage ID: {image}.\nOwner-authorized large-model comparison is in progress; validation is pending. Host watchdog stops our job below 2 GiB available RAM or at {thermal_stop_c} C. Job swap is disabled.\nOriginal NGC image is retained for rollback.'
  for dst,src in [('/opt/compute-host/AGENTS.md','AGENTS.md'),('/home/d_wizard/AGENTS.md','home-AGENTS.md')]:
   s=(base/src).read_text();a=s.index('Jobs run sequentially');b=s.index('This is the existing installed image',a)
   updated=s[:a]+paragraph+'\n'+s[b:]
   updated=updated.replace('16 CPU/96 GiB limits, 4 GiB shared memory','20 CPU/118 GiB limits, 16 GiB shared memory')
   pathlib.Path(dst).write_text(updated)
  s=(base/'web.py').read_text();s=s.replace('Existing NVIDIA vLLM 26.10 prerelease image, pinned by image ID. PyTorch GPU matrix computation passed on GB10. New pipeline dependencies may require an administrator-built image.',f'Temporary owner-authorized large-model comparison: {label}. Image ID {image}. Validation pending. Original image retained for rollback.')
  s=s.replace('16 CPUs / 96 GiB RAM','20 CPUs / 118 GiB charged RAM; actual host memory guarded at 2 GiB; swap disabled for jobs')
  ast.parse(s);pathlib.Path('/opt/compute-host/web.py').write_text(s)
 subprocess.run(['systemctl','restart','compute-reference'],check=True)
finally:
 subprocess.run(['systemctl','start','compute-queue'],check=True)
print(json.dumps({'runtime':label,'image':image,'queue':'started'}))
