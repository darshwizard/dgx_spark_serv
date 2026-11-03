#!/usr/bin/env python3
"""One-shot delayed campaign; no publishing until all models and cleanup pass."""
import datetime,hashlib,importlib.util,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def status(state,**kw):
 p=ROOT/'status.tmp';p.write_text(json.dumps({'state':state,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),**kw},indent=2)+'\n');p.replace(ROOT/'status.json')
def main():
 cfg=json.loads((ROOT/'schedule.json').read_text());repo=Path(cfg['repo']);control=load('run');control.REPO=repo
 if datetime.datetime.now(datetime.timezone.utc)<datetime.datetime.fromisoformat(cfg['start_utc']):raise RuntimeError('Refusing start before scheduled time')
 for path,sha in cfg['host_original_sha256'].items():
  if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise RuntimeError('Host configuration changed since preparation: '+path)
 if subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()!=cfg['source_commit']:raise RuntimeError('Prepared source commit changed')
 if subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip():raise RuntimeError('Prepared checkout is not clean')
 for tag,sha in cfg['images'].items():
  if subprocess.check_output(['docker','image','inspect',tag,'--format','{{.Id}}'],text=True).strip()!=sha:raise RuntimeError('Image tag changed: '+tag)
 for name in ['run.py','switch-runtime.py','publish.py','entry.py','recover.py']:
  if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=cfg['controller_sha256'][name]:raise RuntimeError('Prepared controller changed: '+name)
 control.remote('mkdir -p ~/workspace/code/cap1800-plans')
 for name in ['model_campaign_job.py','paired_model_bench.py']:
  subprocess.run(control.SCP+[str(repo/'scripts'/name),control.HOST+':workspace/code/'],check=True)
 for name in ['qwen27.json','bolt.json']:
  subprocess.run(control.SCP+[str(repo/'configs/cap1800-20261103'/name),control.HOST+':workspace/code/cap1800-plans/'],check=True)
 status('running',models=cfg['models']);(ROOT/'runtime-touched').write_text('owner-authorized scheduled campaign\n')
 try:
  for model in cfg['models']:
   if not control.model_run(model,'01'):raise RuntimeError(model+' did not complete; retaining old headline results')
 finally:load('recover').cleanup()
 status('publishing')
 summary=load('publish').publish(ROOT,repo)
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip();status('complete',commit=commit,models=summary)
 # Refresh the shared main checkout only if it is clean and still at our prepared commit.
 primary=Path('/home/d_wizard/local-ai/dgx_spark_serv')
 if subprocess.check_output(['git','rev-parse','--abbrev-ref','HEAD'],cwd=primary,text=True).strip()=='main' and not subprocess.check_output(['git','status','--porcelain'],cwd=primary,text=True).strip() and subprocess.check_output(['git','rev-parse','HEAD'],cwd=primary,text=True).strip()==cfg['source_commit']:
  subprocess.run(['git','pull','--ff-only'],cwd=primary,check=True)
 with Path('/home/d_wizard/local-ai/forum-watch/memory.txt').open('a') as f:f.write('\nScheduled 1800 MHz four-model campaign COMPLETE; pushed main '+commit+'. Status/artifacts '+str(ROOT)+'/status.json. All models unloaded and host defaults restored. DeepSeek 1017 at 256K still pending.\n')
if __name__=='__main__':
 try:main()
 except BaseException as e:
  status('failed',error=repr(e));raise
