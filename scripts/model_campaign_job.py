#!/usr/bin/env python3
"""Offline queued server for Super VL / Flash-Next benchmark campaign."""
import argparse,datetime as dt,json,os,signal,subprocess,sys,threading,time,urllib.request
from pathlib import Path
ROOT=Path('/workspace');stop=threading.Event();children=[];failures=[]
def stamp():return {'utc':dt.datetime.now(dt.timezone.utc).isoformat(),'monotonic_s':time.monotonic()}
def event(name,**kw):print(json.dumps({**stamp(),'event':name,**kw}),flush=True)
def terminate():
 for p in children:
  if p.poll() is None:
   try:os.killpg(p.pid,signal.SIGTERM)
   except ProcessLookupError:pass
def guard(out):
 with (out/'job-health.jsonl').open('w',buffering=1) as f:
  while not stop.wait(1):
   try:
    zones=[float(x.read_text())/1000 for x in Path('/sys/class/thermal').glob('thermal_zone*/temp')]
    mem={x.split(':')[0]:int(x.split()[1])*1024 for x in Path('/proc/meminfo').read_text().splitlines()}
    avail=mem['MemAvailable'];reason=None
    if len(zones)!=7:reason='missing_thermal_sensors'
    if zones and max(zones)>=90:reason='thermal_limit_90C'
    if avail<2*1024**3:reason='host_available_below_2GiB'
    f.write(json.dumps({**stamp(),'hottest_c':max(zones,default=None),'host_available_bytes':avail,'cgroup':{k:(Path('/sys/fs/cgroup')/k).read_text().strip() for k in ['memory.current','memory.peak','memory.events','cpu.stat']}})+'\n')
   except Exception as e:reason='health_read_error: '+str(e)
   if reason:failures.append(reason);event('guard_abort',reason=reason);terminate();stop.set()
def main():
 p=argparse.ArgumentParser();p.add_argument('--phase-mode',choices=['paired','limited-only','normal-only'],default='paired');p.add_argument('--model',choices=['qwen27','bolt','super','flash'],required=True);p.add_argument('--run-id',required=True);p.add_argument('--limited-profile',choices=['efficiency80','gpu1800_cpu80','gpu1800_cpu60'],default='efficiency80');p.add_argument('--quality-mode',choices=['both','normal-only'],default='both');a=p.parse_args()
 if not a.run_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in a.run_id):p.error('Invalid run ID')
 out=ROOT/'results'/a.run_id;out.mkdir(parents=True,exist_ok=False)
 target=ROOT/'models'/dict(qwen27='Qwen3.8-27B-NVFP4',bolt='NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB',super='NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4',flash='Qwen3.8-Flash-Next-FP4-Local')[a.model]
 command=[sys.executable,'-m','vllm.entrypoints.cli.main','serve',str(target),'--served-model-name','candidate','--host','127.0.0.1','--port','8000','--trust-remote-code','--max-model-len','32768','--max-num-seqs','4','--enable-auto-tool-choice']
 env=os.environ.copy();cache='/workspace/cache/large-'+a.model
 env.update({'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HOME':'/workspace/cache/hf','HF_MODULES_CACHE':'/workspace/cache/hf-modules','PYTHONDONTWRITEBYTECODE':'1','XDG_CACHE_HOME':cache,'TORCHINDUCTOR_CACHE_DIR':cache+'/inductor','TRITON_CACHE_DIR':cache+'/triton','VLLM_CACHE_ROOT':cache+'/vllm','CUDA_CACHE_PATH':cache+'/cuda','VLLM_SERVER_DEV_MODE':'1','VLLM_NO_USAGE_STATS':'1','DO_NOT_TRACK':'1','OMP_NUM_THREADS':'8'})
 env.pop('HF_TOKEN',None)
 if a.model in ['qwen27','bolt']:
  plan=json.loads((ROOT/'code/cap1800-plans'/(a.model+'.json')).read_text())
  command=plan['command'];command[0]=sys.executable
  command[command.index('--served-model-name')+1]='candidate'
  env['VLLM_USE_V2_MODEL_RUNNER']='1'
  for key in ['XDG_CACHE_HOME','TORCHINDUCTOR_CACHE_DIR','TRITON_CACHE_DIR','VLLM_CACHE_ROOT','CUDA_CACHE_PATH']:
   env[key]=env[key].replace(cache,'/workspace/cache/playbook')
 elif a.model=='super':
  draft=ROOT/'models/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4-LiLiCorr'
  command+=['--gpu-memory-utilization','0.75','--max-num-batched-tokens','8192','--speculative-config',json.dumps({'method':'dflash','model':str(draft),'num_speculative_tokens':7}),'--mamba-backend','flashinfer','--mamba-ssm-cache-dtype','float16','--enable-mamba-cache-stochastic-rounding','--mamba-cache-philox-rounds','5','--enable-mamba-shared-prefix-checkpoint','--block-size','64','--prefix-match-unit','64','--limit-mm-per-prompt',json.dumps({'image':1,'video':0}),'--allowed-media-domains','media.invalid','--tool-call-parser','qwen3_coder','--reasoning-parser','nemotron_v3','--enable-prompt-tokens-details']
 else:
  env.update({'PYTORCH_CUDA_ALLOC_CONF':'expandable_segments:True','VLLM_PLE_TABLE_MEMORY':'disk','B12X_DISK_BACKEND':'io_uring','CUTE_DSL_ARCH':'sm_121a','SAFETENSORS_FAST_GPU':'1','VLLM_WORKER_MULTIPROC_METHOD':'spawn','VLLM_SSM_CONV_STATE_LAYOUT':'DS','VLLM_USE_AOT_COMPILE':'1','VLLM_USE_MEGA_AOT_ARTIFACT':'1','VLLM_USE_V2_MODEL_RUNNER':'1','B12X_POLICY_MODE':'auto','VLLM_MXFP8_LM_HEAD':'1','VLLM_B12X_MOE_FP4_LAYER_MAX_INPUT_SCALE':'w13','VLLM_B12X_MOE_FP4_FORCE_A16':'1','B12X_W4A16_A4_PREFILL':'1'})
  command+=['--kv-cache-dtype','fp8','--gpu-memory-utilization','0.8','--tensor-parallel-size','1','--pipeline-parallel-size','1','--mamba-cache-mode','align','--enable-prefix-caching','--enable-chunked-prefill','--dtype','bfloat16','--quantization','modelopt_mixed','--block-size','16','--load-format','b12x','--max-num-batched-tokens','4096','--speculative-config',json.dumps({'method':'mtp','num_speculative_tokens':4}),'--gdn-decode-kernel','b12x','--linear-backend','b12x','--moe-backend','b12x','--no-enable-flashinfer-autotune','--mm-encoder-tp-mode','data','--reasoning-parser','qwen3','--tool-call-parser','qwen3_xml','--compilation-config',json.dumps({'pass_config':{'fuse_act_quant':True}})]
 (out/'launch.json').write_text(json.dumps({'command':command,'model':a.model,'environment':{k:v for k,v in env.items() if k.startswith(('VLLM_','B12X_','OMP_','CUTE_','SAFETENSORS_','PYTORCH_'))},'queue_limits':{'memory_gib':118,'cpus':20,'shm_gib':16},'thermal_stop_c':90,'memory_stop_available_gib':2},indent=2))
 def signal_stop(*_):failures.append('signal');stop.set();terminate()
 signal.signal(signal.SIGTERM,signal_stop);signal.signal(signal.SIGINT,signal_stop)
 watcher=threading.Thread(target=guard,args=(out,),daemon=True);watcher.start();rc=1
 try:
  with (out/'server.log').open('w',buffering=1) as f:
   event('server_start');server=subprocess.Popen(command,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True);children.append(server)
   start=time.monotonic();ready=False;next_beat=0
   while server.poll() is None and not stop.is_set() and time.monotonic()-start<2700:
    try:
     with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2) as r:ready=r.status==200
     if ready:break
    except Exception:pass
    if time.monotonic()>=next_beat:event('warming_server',elapsed_s=round(time.monotonic()-start));next_beat=time.monotonic()+30
    stop.wait(2)
   if ready and not stop.is_set():
    event('server_ready',startup_s=time.monotonic()-start)
    bench=subprocess.Popen([sys.executable,'/workspace/code/paired_model_bench.py','--out',str(out/'bench'),'--tokenizer',str(target),'--limited-profile',a.limited_profile,'--quality-mode',a.quality_mode,'--phase-mode',a.phase_mode],env=env,start_new_session=True);children.append(bench);rc=bench.wait()
   else:failures.append('server_not_ready')
 finally:
  stop.set();terminate()
  for c in children:
   try:c.wait(timeout=20)
   except subprocess.TimeoutExpired:os.killpg(c.pid,signal.SIGKILL);c.wait()
  watcher.join(timeout=5)
  if failures:rc=1
  (out/'outcome.json').write_text(json.dumps({'exit_code':rc,'failures':failures,**stamp()},indent=2));event('job_finished',exit_code=rc,failures=failures)
 return rc
if __name__=='__main__':raise SystemExit(main())
