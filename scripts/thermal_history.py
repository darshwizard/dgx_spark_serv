#!/usr/bin/env python3
"""Analyze archived sensor traces without running inference or changing controls.

Run with Python + matplotlib: python scripts/thermal_history.py
Reads committed raw archives; writes a plot, per-workload CSV and JSON summary.
"""
import argparse
import csv
import gzip
import json
import statistics
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CPU_ZONES = ['TS0E', 'TS0P', 'TS1E', 'TS1P']


def load_run(key):
    if key in ['super', 'flash-next']:
        archive = REPO / 'experiments/large-models-20261102' / key / 'raw-run.tar.gz'
        with tarfile.open(archive) as tf:
            def read(suffix):
                names = [n for n in tf.getnames() if n.endswith(suffix)]
                assert len(names) == 1, (suffix, names)
                return [json.loads(x) for x in tf.extractfile(names[0])]
            raw = read('/telemetry/sensors.jsonl')
            events = read('/result/bench/events.jsonl')
    else:
        folder = 'telemetry-02' if key == 'qwen' else 'telemetry'
        archive = REPO / f'experiments/{key}-standard-20261102' / folder / 'sensors.jsonl.gz'
        with gzip.open(archive, 'rt') as f:
            raw = [json.loads(x) for x in f]
        events = []
    rows = []
    for r in raw:
        zones = {z['acpi_path'].rsplit('.', 1)[-1]: z['celsius'] for z in r['thermal_zones']}
        assert all(zones.get(k) is not None for k in CPU_ZONES + ['TGPU', 'TSOC'])
        gpu = r['gpus'][0]['temperature.gpu'] if len(r['gpus']) == 1 else None
        rows.append({'utc': r['utc'], 'monotonic_s': r['monotonic_s'],
                     'minute': (r['monotonic_s'] - raw[0]['monotonic_s']) / 60,
                     'cpu_zone_max_c': max(zones[k] for k in CPU_ZONES),
                     'acpi_gpu_c': zones['TGPU'], 'nvml_gpu_c': gpu,
                     'soc_c': zones['TSOC']})
    return rows, events, str(archive.relative_to(REPO))


def summarize(rows):
    delta = [r['cpu_zone_max_c'] - r['acpi_gpu_c'] for r in rows]
    return {'samples': len(rows),
            'cpu_zone_peak_c': max(r['cpu_zone_max_c'] for r in rows),
            'acpi_gpu_peak_c': max(r['acpi_gpu_c'] for r in rows),
            'nvml_gpu_peak_c': max(r['nvml_gpu_c'] for r in rows if r['nvml_gpu_c'] is not None),
            'mean_cpu_minus_acpi_gpu_c': statistics.mean(delta),
            'cpu_hotter_by_over_1c_fraction': sum(x > 1 for x in delta) / len(delta),
            'gpu_hotter_by_over_1c_fraction': sum(x < -1 for x in delta) / len(delta),
            'largest_cpu_lead': max(rows, key=lambda r: r['cpu_zone_max_c'] - r['acpi_gpu_c']),
            'largest_gpu_lead': min(rows, key=lambda r: r['cpu_zone_max_c'] - r['acpi_gpu_c'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=REPO / 'experiments/thermal-history-20261103')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    fig = plt.figure(figsize=(13, 12), layout='constrained')
    grid = fig.add_gridspec(3, 2, height_ratios=[1, 1, 0.9])
    summaries, phases, loaded = {}, [], {}
    for i, (key, label) in enumerate([('qwen', 'Qwen 27B'), ('bolt', 'Nemotron Bolt'),
                                      ('super', 'Nemotron Super VL'), ('flash-next', 'Qwen Flash Next')]):
        rows, events, source = load_run(key)
        loaded[key] = rows
        summaries[key] = {'source': source, **summarize(rows)}
        ax = fig.add_subplot(grid[i // 2, i % 2])
        for field, color, title, style in [
            ('cpu_zone_max_c', '#c94a35', 'Hottest CPU-labelled ACPI zone', '-'),
            ('acpi_gpu_c', '#2468b4', 'ACPI GPU zone (TGPU)', '-'),
            ('nvml_gpu_c', '#777777', 'nvidia-smi GPU', '--')]:
            ax.plot([r['minute'] for r in rows], [r[field] for r in rows],
                    color=color, lw=0.8, ls=style, label=title, alpha=0.9)
        t0 = rows[0]['monotonic_s']
        ready = [e for e in events if e['event'] == 'profile_ready']
        for j, e in enumerate(ready):
            end = ready[j + 1]['monotonic_s'] if j + 1 < len(ready) else rows[-1]['monotonic_s']
            if e['profile'] == 'efficiency80':
                ax.axvspan((e['monotonic_s'] - t0) / 60, (end - t0) / 60,
                           color='#80b28a', alpha=0.18, lw=0)
        profile, seq = None, None
        for e in events:
            if e['event'] == 'profile_ready':
                profile, seq = e['profile'], e['seq']
            elif e['event'] == 'workload_start':
                end = next(x for x in events if x['event'] == 'workload_end'
                           and x['monotonic_s'] > e['monotonic_s'])
                selected = [r for r in rows if e['monotonic_s'] <= r['monotonic_s'] <= end['monotonic_s']]
                s = summarize(selected)
                phases.append({'model': key, 'seq': seq, 'profile': profile, 'workload': e['label'],
                               'start_minute': (e['monotonic_s'] - t0) / 60,
                               'duration_s': end['monotonic_s'] - e['monotonic_s'],
                               **{k: v for k, v in s.items() if not isinstance(v, dict)}})
                if e['label'] == 'throughput':
                    ax.axvline((e['monotonic_s'] - t0) / 60, color='#555555', lw=0.7, ls=':')
        ax.set(title=label + (' — earlier protocol' if not events else ' — paired protocol'),
               xlabel='Minutes since telemetry began', ylabel='Temperature (°C)', ylim=(35, 95))
        ax.grid(alpha=0.2)
    zoom = fig.add_subplot(grid[2, :])
    rows = [r for r in loaded['flash-next'] if 6 <= r['minute'] <= 9]
    for field, color in [('cpu_zone_max_c', '#c94a35'), ('acpi_gpu_c', '#2468b4'), ('nvml_gpu_c', '#777777')]:
        zoom.plot([r['minute'] for r in rows], [r[field] for r in rows], color=color, lw=1)
    zoom.set(title='Flash Next startup detail: CPU and GPU peaks occur 44 seconds apart',
             xlabel='Minutes since telemetry began', ylabel='Temperature (°C)', ylim=(45, 85))
    zoom.grid(alpha=0.2)
    handles, labels = fig.axes[0].get_legend_handles_labels()
    handles += [Patch(facecolor='#80b28a', alpha=0.3, label='Limited-profile phase windows (paired panels only)')]
    fig.legend(handles=handles, loc='outside upper center', ncol=2, fontsize=9,
               title='Measured thermal histories, Nov 2–3, 2026 — unsmoothed ~1-second samples\n'
                     'CPU = max(TS0E, TS0P, TS1E, TS1P); old limit = GPU 2,402 MHz / CPU 80%')
    fig.savefig(args.out / 'temperature-timelines.png', dpi=160)
    fig.savefig(args.out / 'temperature-timelines.svg')
    (args.out / 'summary.json').write_text(json.dumps(summaries, indent=2) + '\n')
    with (args.out / 'workload-temperatures.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(phases[0]))
        writer.writeheader()
        writer.writerows(phases)
    print('Wrote thermal histories, summaries and per-workload CSV:', args.out)


if __name__ == '__main__':
    main()
