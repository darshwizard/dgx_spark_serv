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
 for limited,quality_mode,quality_count in [('efficiency80','both',2),('gpu1800_cpu80','normal-only',1),('gpu1800_cpu60','normal-only',1)]:
  calls.clear();API.resets=0
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
    with patch.object(sys,'argv',['paired_model_bench.py','--out',str(out),'--tokenizer','offline-model','--limited-profile',limited,'--quality-mode',quality_mode]),patch('subprocess.call',process),contextlib.redirect_stdout(io.StringIO()):main()
    events=[json.loads(x) for x in (out/'events.jsonl').read_text().splitlines()]
    assert [e['profile'] for e in events if e['event']=='profile_ready']==['normal',limited,limited,'normal']
    assert sum(e['event']=='workload_start' for e in events)==4+quality_count
    assert sum(e['event']=='workload_end' for e in events)==4+quality_count
    assert API.resets==4+quality_count and len(calls)==4+quality_count
    assert sum(c[0]=='tool-eval-bench' for c in calls)==quality_count
    assert sum('--exact-tg' in c for c in calls)==4
    assert (out/'completed.json').exists()
    print(f'PASS: {limited}, quality={quality_mode}, four phases and complete workload/reset events')
   finally:stop.set();t.join()
finally:server.shutdown();server.server_close()
