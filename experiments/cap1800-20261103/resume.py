#!/usr/bin/env python3
"""Continue unattempted models after a recorded thermal stop; never rerun it."""
import hashlib,importlib.util,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def main():
 cfg=json.loads((ROOT/'schedule.json').read_text());repo=Path(cfg['repo']);entry=load('entry');control=load('run');control.REPO=repo
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==cfg['source_commit']
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip()
 for path,sha in cfg['host_original_sha256'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha,path
 for name,sha in cfg['controller_sha256'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
 for tag,sha in cfg['images'].items():assert subprocess.check_output(['docker','image','inspect',tag,'--format','{{.Id}}'],text=True).strip()==sha,tag
 assert json.loads((ROOT/'qwen27-gpu1800-01/result/outcome.json').read_text())['exit_code']==0
 assert json.loads((ROOT/'bolt-gpu1800-01/watchdog/abort.json').read_text())['reason']=='thermal_limit_90C'
 failed=['bolt']
 try:
  for model in ['super','flash']:
   entry.status('running',current_model=model,completed=['qwen27'],thermal_stopped=failed)
   if not control.model_run(model,'01'):failed.append(model)
 finally:load('recover').cleanup()
 entry.status('publishing',incomplete=failed)
 summary=load('publish').publish(ROOT,repo)
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
 entry.status('complete_with_thermal_stop',commit=commit,models=summary)
 primary=Path('/home/d_wizard/local-ai/dgx_spark_serv')
 if not subprocess.check_output(['git','status','--porcelain'],cwd=primary,text=True).strip():subprocess.run(['git','pull','--ff-only'],cwd=primary,check=True)
 with Path('/home/d_wizard/local-ai/forum-watch/memory.txt').open('a') as f:f.write('\nCPU60 campaign published '+commit+'; complete comparisons plus explicitly archived thermal-stopped runs. Defaults restored.\n')
if __name__=='__main__':
 try:main()
 except BaseException as e:load('entry').status('failed',error=repr(e));raise
