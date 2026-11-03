#!/usr/bin/env python3
"""Exercise real profile logic against temporary files; never touch clocks."""
import contextlib,io,runpy,sys,tempfile
from pathlib import Path
from unittest.mock import patch
for explicit,expected in [(None,2402),(1800,1800)]:
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);p=root/'policy0';p.mkdir()
  original={'scaling_min_freq':338000,'scaling_max_freq':2808000,'cpuinfo_max_freq':2808000}
  for k,v in original.items():(p/k).write_text(str(v))
  calls=[]
  def gpu(*args):
   calls.append(args)
   return '3003' if args[0].startswith('--query-gpu') else 'mock clocks'
  def cpu():return {str(p):{k:int((p/k).read_text()) for k in original}}
  main=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/clock_profile.py'))['main'];main.__globals__.update(gpu=gpu,cpu=cpu)
  argv=['clock_profile.py','apply','--state',str(root/'state.json'),'--gpu-default-baseline']
  if explicit:argv+=['--gpu-max-mhz',str(explicit)]
  with patch.object(sys,'argv',argv),patch('os.geteuid',return_value=0),contextlib.redirect_stdout(io.StringIO()):main()
  assert ('-lgc','0,'+str(expected)) in calls
  assert int((p/'scaling_max_freq').read_text())==2246400
  with patch.object(sys,'argv',['clock_profile.py','restore','--state',str(root/'state.json')]),patch('os.geteuid',return_value=0),contextlib.redirect_stdout(io.StringIO()):main()
  assert cpu()[str(p)]==original and ('-rgc',) in calls
print('PASS: explicit 1800 MHz and historical default; CPU80; exact CPU restoration and GPU reset, all mocked')
