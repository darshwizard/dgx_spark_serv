#!/usr/bin/env python3
"""Run via compute-job before attempting model load. No package installation."""
import importlib
import importlib.metadata as md
import json
import os
import platform
from pathlib import Path
import subprocess
import sys

result = {'hostname': platform.node(), 'python': platform.python_version(),
          'packages': {}, 'imports': {}, 'cgroup': {}}
for name in ['torch', 'vllm', 'b12x', 'flashinfer-python', 'transformers', 'triton', 'nvidia-modelopt']:
    try:
        result['packages'][name] = md.version(name)
    except md.PackageNotFoundError:
        result['packages'][name] = None
for name in ['torch', 'vllm', 'b12x', 'flashinfer']:
    try:
        module = importlib.import_module(name)
        result['imports'][name] = 'ok'
    except Exception as e:
        result['imports'][name] = f'{type(e).__name__}: {e}'
for name in ['memory.max', 'memory.current', 'memory.peak', 'memory.events', 'cpu.max']:
    try:
        result['cgroup'][name] = Path('/sys/fs/cgroup', name).read_text().strip()
    except OSError:
        result['cgroup'][name] = None
if result['imports']['torch'] == 'ok':
    import torch
    result['cuda_available'] = torch.cuda.is_available()
    if result['cuda_available']:
        result['gpu_name'] = torch.cuda.get_device_name(0)
        # Tiny bounded correctness check, not a thermal or throughput benchmark.
        a = torch.arange(16, device='cuda', dtype=torch.float32).reshape(4, 4)
        result['cuda_matmul_correct'] = torch.equal((a @ torch.eye(4, device='cuda')).cpu(), a.cpu())
result['vllm_help'] = subprocess.run(['python3', '-m', 'vllm.entrypoints.cli.main', 'serve', '--help'],
                                    text=True, capture_output=True, timeout=120).returncode
out = Path(sys.argv[1] if len(sys.argv)>1 else '/workspace/results/bolt-runtime-probe.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2), flush=True)
raise SystemExit(0 if all(v == 'ok' for v in result['imports'].values())
                 and result.get('cuda_matmul_correct') and result['vllm_help'] == 0 else 2)
