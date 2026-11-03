Completed Super VL and Flash Next experiments, November 2-3, 2026

Start with ../../docs/LARGE-MODEL-RESULTS-20261103.txt and the front README.
summary.json: quality, two-pass energy/time and memory/temperature summaries.
throughput-matrix.csv: every measured depth/concurrency/profile, pooled SD.
Each model directory: exact launch/spec, profile readbacks, full readable quality
reports, four throughput JSON files, workload/telemetry/startup summaries, and a
raw-run.tar.gz containing the full result logs, telemetry and watchdog evidence.
Extract an archive from this directory with tar -xzf MODEL/raw-run.tar.gz.
No model weights or credentials are included. Image and model pins are explicit.

Source metadata refers to real retained Git commits; all recorded source hashes
were checked against those commits. Current analysis is scripts/workload_energy.py.
The run.py owner controller and switch-runtime.py helper are host-specific
examples, with local paths, SSH account/key paths and rollback locations. Adapt
them to another installation; do not execute them against an unrelated host.
See the recipe report for build/staging and the server-only launch configuration.

startup-failures/ preserves six failed starts separately. Super 01/02 were
conservative swap-only guard stops; Super 03/04 were harness bugs before quality.
Flash 05/06 were RAM-pressure stops during weight repacking, fixed on this pairing
by the community expandable-segments allocator setting in successful Flash 07.
Those attempts yield no quality scores. Super 05 and Flash 07 both exited 0.

telemetry-summary interrupted=true means the read-only logger was intentionally
stopped with SIGTERM after job completion; inspect job outcome/spec/status for
actual job state. GPU-reported energy is not whole-machine energy. Disk/CPU
activity is host-wide. No ambient sensor or wall wattmeter was available.
