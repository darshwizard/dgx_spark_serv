#!/usr/bin/env python3
"""CPU-only end-to-end orchestration regression, mocked workload processes."""
import contextlib,http.server,io,json,runpy,sys,tempfile,threading,time
from pathlib import Path
from unittest.mock import patch
calls=[]
class API(http.server.BaseHTTPRequestHandler):
 resets=0
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write(b'{}' if self.path=='/v1/models' else b'vllm:generation_tokens_total 0\n')
 def do_POST(self):
  assert self.path=='/reset_prefix_cache';type(self).resets+=1
  self.send_response(200);self.end_headers();self.wfile.write(b'{"success":true}')
 def log_message(self,*_):pass
def process(cmd,**kw):calls.append(cmd);return 0
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),API)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with tempfile.TemporaryDirectory() as tmp:
  out=Path(tmp)/'bench';stop=threading.Event()
  def controller():
   while not stop.wait(.01):
    p=out/'phase-request.json'
    if p.exists():
     req=json.loads(p.read_text());ack=out/f'phase-{req["seq"]}-ack.json'
     if not ack.exists():
      q=ack.with_suffix('.tmp');q.write_text(json.dumps({**req,'ready':True}));q.replace(ack)
  t=threading.Thread(target=controller);t.start()
  try:
   main=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/paired_model_bench.py'))['main']
   main.__globals__['BASE']=f'http://127.0.0.1:{server.server_port}'
   with patch.object(sys,'argv',['paired_model_bench.py','--out',str(out),'--tokenizer','offline-model']),patch('subprocess.call',process),contextlib.redirect_stdout(io.StringIO()):main()
   events=[json.loads(x) for x in (out/'events.jsonl').read_text().splitlines()]
   assert [e['profile'] for e in events if e['event']=='profile_ready']==['normal','efficiency80','efficiency80','normal']
   assert sum(e['event']=='workload_start' for e in events)==6
   assert sum(e['event']=='workload_end' for e in events)==6
   assert API.resets==6 and len(calls)==6
   assert sum(c[0]=='tool-eval-bench' for c in calls)==2
   assert sum('--exact-tg' in c for c in calls)==4
   assert (out/'completed.json').exists()
   print('PASS: all four profile handshakes, two quality suites, four throughput suites, six successful resets and complete event pairs')
  finally:stop.set();t.join()
finally:server.shutdown();server.server_close()
