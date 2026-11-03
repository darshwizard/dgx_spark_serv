#!/usr/bin/env python3
"""Temporary clock controls for a reserved host. Run as owner/root, not in a job.

GPU restore resets to DEFAULT, not an unknown pre-existing lock. Use only after
establishing that default clocks are the intended baseline. CPU limits restored
exactly from the saved file. No persistent service or firmware modifications.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def gpu(*args):
    p=subprocess.run(['nvidia-smi',*args],text=True,capture_output=True,timeout=15)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout.strip()


def cpu():
    return {str(p):{k:int((p/k).read_text()) for k in
                    ['scaling_min_freq','scaling_max_freq','cpuinfo_max_freq']}
            for p in Path('/sys/devices/system/cpu/cpufreq').glob('policy*')}


def restore(state):
    errors=[]
    for path,values in state['cpu'].items():
        try:
            p=Path(path)
            # Raise max first if the original minimum is above the current cap.
            (p/'scaling_max_freq').write_text(str(values['scaling_max_freq']))
            (p/'scaling_min_freq').write_text(str(values['scaling_min_freq']))
            # CPPC readback may lag the write; allow a bounded settling period.
            for _ in range(50):
                if all(int((p/k).read_text())==values[k] for k in
                       ['scaling_max_freq','scaling_min_freq']):
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError('CPU limits did not settle to saved values within 5 seconds')
        except Exception as e: errors.append(f'{path}: {e}')
    try: gpu('-rgc')
    except Exception as e: errors.append(str(e))
    if errors: raise RuntimeError('; '.join(errors))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['apply','restore'])
    p.add_argument('--state',type=Path,required=True)
    p.add_argument('--gpu-default-baseline',action='store_true')
    p.add_argument('--gpu-max-mhz',type=int,help='Explicit GPU ceiling in MHz; omitted preserves the historical 80%% profile')
    args=p.parse_args()
    if args.gpu_max_mhz is not None and args.gpu_max_mhz<=0:
        p.error('GPU ceiling must be positive')
    if os.geteuid()!=0: p.error('Owner/root privileges required')
    if args.action=='restore':
        state=json.loads(args.state.read_text())
        if state['boot_id']!=Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            p.error('Boot changed; review saved limits before restoring')
        restore(state)
        print(json.dumps({'restored':True,'cpu':cpu(),'gpu':gpu('-q','-d','CLOCK')}))
        return
    if not args.gpu_default_baseline:
        p.error('Must establish a default GPU baseline; unknown locks cannot be restored')
    if args.state.exists(): p.error('State exists; refusing to overwrite rollback record')
    state={'cpu':cpu(),'gpu_before':gpu('-q','-d','CLOCK'),
           'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
           'created_unix_s':time.time(),'gpu_restore':'reset to explicitly established defaults'}
    args.state.parent.mkdir(parents=True,exist_ok=True)
    args.state.write_text(json.dumps(state,indent=2)+'\n')
    args.state.chmod(0o644)
    try:
        maximum=int(gpu('--query-gpu=clocks.max.sm','--format=csv,noheader,nounits'))
        target=args.gpu_max_mhz if args.gpu_max_mhz is not None else int(maximum*0.8)
        if target>maximum:raise RuntimeError('Requested GPU ceiling exceeds reported hardware maximum')
        for path,values in state['cpu'].items():
            cap=int(values['cpuinfo_max_freq']*0.8)
            # Never increase an existing lower cap.
            cap=min(cap,values['scaling_max_freq'])
            q=Path(path)
            if values['scaling_min_freq']>cap:
                (q/'scaling_min_freq').write_text(str(cap))
            (q/'scaling_max_freq').write_text(str(cap))
        applied=gpu('-lgc',f'0,{target}')
        after=cpu()
        for path,values in after.items():
            if values['scaling_max_freq']>int(values['cpuinfo_max_freq']*0.8):
                raise RuntimeError('CPU frequency cap readback above requested limit')
        print(json.dumps({'gpu_requested_max_mhz':target,'gpu_response':applied,
                          'cpu_after':after,'note':'Validate observed GPU clocks under load.'}))
    except BaseException:
        restore(state)
        raise


if __name__=='__main__': main()
