#!/usr/bin/env python3
"""Read-only GB10 host telemetry. No workloads, privilege changes, or control writes.

Run outside the job container to see host sensors. Output is exclusive per run.
SIGINT/SIGTERM flush a summary. Thermal alarms are logged; this is not a watchdog.
"""
import argparse
import csv
import datetime as dt
import json
import platform
from pathlib import Path
import signal
import subprocess
import time

FIELDS = ['uuid', 'pstate', 'utilization.gpu', 'utilization.memory',
          'temperature.gpu', 'power.draw', 'clocks.sm', 'clocks.gr',
          'clocks_event_reasons.sw_power_cap',
          'clocks_event_reasons.sw_thermal_slowdown',
          'clocks_event_reasons.hw_thermal_slowdown',
          'clocks_event_reasons.hw_power_brake_slowdown']
STOP = False


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def number(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'error': str(e)}


def cpu_policies():
    return {p.name: {name: read(p / name) for name in
                    ['related_cpus', 'scaling_driver', 'scaling_governor',
                     'cpuinfo_min_freq', 'cpuinfo_max_freq', 'scaling_min_freq',
                     'scaling_max_freq', 'scaling_cur_freq']}
            for p in sorted(Path('/sys/devices/system/cpu/cpufreq').glob('policy*'))}


def snapshot():
    start = time.monotonic()
    row = {'utc': utc(), 'monotonic_s': start}
    result = command(['nvidia-smi', '--query-gpu=' + ','.join(FIELDS),
                      '--format=csv,noheader,nounits'])
    row['gpus'] = []
    if result.get('returncode') == 0:
        for values in csv.reader(result['stdout'].splitlines(), skipinitialspace=True):
            if len(values) != len(FIELDS):
                row['gpu_error'] = 'Unexpected nvidia-smi column count'
                continue
            row['gpus'].append({k: number(v) if k in FIELDS[2:8] else v
                                for k, v in zip(FIELDS, values)})
    else:
        row['gpu_error'] = result
    row['thermal_zones'] = []
    for p in sorted(Path('/sys/class/thermal').glob('thermal_zone*')):
        temp = number(read(p / 'temp'))
        row['thermal_zones'].append({'id': p.name, 'type': read(p / 'type'),
                                    'acpi_path': read(p / 'device/path'),
                                    'celsius': temp / 1000 if temp is not None else None})
    row['hwmon'] = []
    for p in sorted(Path('/sys/class/hwmon').glob('hwmon*')):
        # Both fans have the same chip name: keep IDs and paths, never key by name.
        sensors = {}
        for f in sorted(p.glob('*_input')):
            if f.name.startswith(('fan', 'temp', 'power', 'energy')):
                sensors[f.name] = {'raw': number(read(f)),
                                   'label': read(f.with_name(f.name.replace('_input', '_label')))}
        row['hwmon'].append({'id': p.name, 'name': read(p / 'name'),
                             'device': str(p.resolve()), 'sensors': sensors})
    row['cpu_policies_khz'] = cpu_policies()
    row['meminfo_kib'] = {}
    for line in (read('/proc/meminfo') or '').splitlines():
        key, value = line.split(':', 1)
        if key in {'MemTotal', 'MemAvailable', 'MemFree', 'Cached', 'SwapTotal',
                   'SwapFree', 'Dirty', 'Writeback'}:
            row['meminfo_kib'][key] = int(value.split()[0])
    row['pressure'] = {name: read('/proc/pressure/' + name)
                       for name in ['cpu', 'memory', 'io']}
    row['proc_stat'] = read('/proc/stat')
    row['diskstats'] = read('/proc/diskstats')
    row['loadavg'] = read('/proc/loadavg')
    row['vmstat'] = {k: int(v) for line in (read('/proc/vmstat') or '').splitlines()
                     for k, v in [line.split()]
                     if k in {'pswpin', 'pswpout', 'pgmajfault', 'oom_kill'}}
    row['sample_duration_s'] = time.monotonic() - start
    return row


def summarize(rows, interval):
    def stats(values):
        return {'min': min(values), 'max': max(values), 'mean': sum(values)/len(values)} if values else None
    temps = [z['celsius'] for r in rows for z in r['thermal_zones'] if z['celsius'] is not None]
    power = [g['power.draw'] for r in rows for g in r['gpus'] if g['power.draw'] is not None]
    energy = covered = 0.0
    for a, b in zip(rows, rows[1:]):
        gap = b['monotonic_s'] - a['monotonic_s']
        if gap > 2.5 * interval or len(a['gpus']) != 1 or len(b['gpus']) != 1:
            continue
        x, y = a['gpus'][0]['power.draw'], b['gpus'][0]['power.draw']
        if x is not None and y is not None:
            energy += (x+y)/2 * gap
            covered += gap
    return {'samples': len(rows), 'gpu_error_samples': sum('gpu_error' in r for r in rows),
            'sample_duration_s': stats([r['sample_duration_s'] for r in rows]),
            'thermal_zone_celsius': stats(temps), 'gpu_reported_power_w': stats(power),
            'min_mem_available_gib': min((r['meminfo_kib']['MemAvailable']/1048576
                                         for r in rows if 'MemAvailable' in r['meminfo_kib']), default=None),
            'gpu_reported_energy_j': energy if covered else None,
            'energy_coverage_s': covered,
            'energy_note': 'Approximate trapezoidal integration of GPU-reported power. Not wall/system energy; long gaps excluded.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=60)
    parser.add_argument('--interval', type=float, default=1)
    parser.add_argument('--label', default='unspecified')
    parser.add_argument('--job-id', default=None)
    parser.add_argument('--alarm-c', type=float, default=90)
    args = parser.parse_args()
    if args.duration <= 0 or args.interval < 0.2:
        parser.error('duration must be positive and interval >= 0.2 seconds')
    args.out.mkdir(parents=True, exist_ok=False)
    metadata = {'schema_version': 1, 'started_utc': utc(), 'hostname': platform.node(),
                'kernel': platform.release(), 'boot_id': read('/proc/sys/kernel/random/boot_id'),
                'label': args.label, 'job_id': args.job_id, 'interval_s': args.interval,
                'duration_s': args.duration, 'alarm_c': args.alarm_c,
                'cpu_policies_at_start': cpu_policies(), 'os_release': read('/etc/os-release'),
                'gpu_inventory': command(['nvidia-smi', '-q', '-x']),
                'repo_commit': command(['git', 'rev-parse', 'HEAD']),
                'repo_dirty': command(['git', 'status', '--porcelain']),
                'sensor_units': {'temp_input': 'millidegrees Celsius', 'fan_input': 'RPM',
                                 'power_input': 'microwatts', 'energy_input': 'microjoules'},
                'warning': 'Read-only logger; alarm does not cancel a job or enforce a cutoff.'}
    (args.out / 'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    def stop(*_):
        global STOP
        STOP = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    start = time.monotonic()
    rows = []
    with (args.out / 'sensors.jsonl').open('w', buffering=1) as log:
        while not STOP and time.monotonic() - start < args.duration:
            row = snapshot()
            hot = max((z['celsius'] for z in row['thermal_zones'] if z['celsius'] is not None), default=None)
            row['thermal_alarm'] = hot is not None and hot >= args.alarm_c
            log.write(json.dumps(row)+'\n')
            rows.append(row)
            remaining = min(start+args.duration, row['monotonic_s']+args.interval) - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
    result = summarize(rows, args.interval)
    result.update({'ended_utc': utc(), 'interrupted': STOP,
                   'thermal_alarm_samples': sum(r['thermal_alarm'] for r in rows)})
    (args.out / 'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
