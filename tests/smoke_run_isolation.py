#!/usr/bin/env python3
"""Regression: stale remote run output must not launch a job or change runtime."""
import runpy,tempfile
from pathlib import Path
from unittest.mock import patch

source=Path(__file__).resolve().parents[1]
ns=runpy.run_path(str(source/'configs/cap1800-20261103/automation/run.py'))
assert ns['run_label']('bolt','01')=='bolt-gpu1800-01'
assert ns['run_label']('bolt','01',True)=='bolt-gpu1800limited-01'
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp);calls=[];g=ns['model_run'].__globals__
 with patch.dict(g,ROOT=root,remote=lambda cmd:calls.append(cmd) or 'exists\n',switch=lambda *args:(_ for _ in ()).throw(AssertionError('Runtime must remain unchanged'))):
  try:ns['model_run']('bolt','01',limited_only=True)
  except RuntimeError as e:assert 'Remote run output already exists' in str(e)
  else:raise AssertionError('Stale output must be rejected before submission')
 assert len(calls)==1 and 'bolt-gpu1800limited-01' in calls[0]
 assert not list(root.iterdir())
print('PASS: limited-only run IDs isolated; stale output rejected before runtime changes/submission')
