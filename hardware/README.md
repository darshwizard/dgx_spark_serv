# DGX Spark (GB10) platform notes — firmware, power, thermals, crashes

Hardware- and firmware-level findings from operating one DGX Spark hard, kept
separate from the [model benchmarks](../README.md) because they apply to **any**
GB10 workload. If your Spark is mysteriously slow or crashing under load, start here.

TL;DR: this unit shipped with a firmware power-delivery fault that silently
capped it at ~15 W (2–3× slowdown) and caused spontaneous hard power-offs under
sustained load. **Updating all firmware via `fwupdmgr` resolved both.** Details,
detection, and the interim workaround below.

---

## 1. The power-clamp bug (the big one)

**Symptom.** Under any GPU load the SM clock pins at ~560–572 MHz (of 3003 max)
and power at ~15 W, with GPU `T.Limit` frozen at ~50–55 °C despite a cool chip,
and the `SW Power Capping` event counter steadily accumulating. A pure BF16 matmul
burn hit only **25.9 TFLOPS** while clamped.

**Impact.** Every throughput number is 2–3× below true capability. This silently
corrupted a full night of benchmarks before we caught it (e.g. a model measured
24–28 tok/s decode vs its author's 45–52 on identical hardware+image). **If you
benchmark a GB10, verify clocks before trusting any number.**

**Root cause.** A firmware / power-delivery state corruption drops the power
controller into a USB-C-PD-style low-power profile — the PD controller's mailbox
interface failing to load at boot, per community analysis. It is *triggered by a
crash during heavy load*, so it tends to appear right after the box falls over.
Matches the NVIDIA forum thread ["GPU Trapped in 15W/650MHz Loop"](https://forums.developer.nvidia.com/t/-/370304)
(NVIDIA acknowledged, under investigation as of mid-2026).

**Detect it:**
```bash
# Under load: healthy clocks ramp toward 2400–3000 MHz, power well above 15 W.
nvidia-smi --query-gpu=clocks.sm,power.draw,temperature.gpu --format=csv

# A growing "SW Power Capping" counter, and T.Limit pinned ~50–55 °C = clamped.
nvidia-smi -q -d PERFORMANCE | grep -A2 -i 'power cap\|t.limit'
```
Diagnostic helper (read-only): [joeynyc/spark-doctor](https://github.com/joeynyc/spark-doctor).

**Interim workaround (before the firmware fix).** A **full 10-minute AC unplug** —
clean shutdown, then pull *both* the unit and its power brick from the wall for
10+ minutes — clears the corrupted PD state. **A warm reboot does NOT** (confirmed;
a crash-triggered reboot left it clamped). This restored 25.9 → **96.7 TFLOPS** (3.7×).

---

## 2. Spontaneous hard power-offs under sustained load

~30 minutes after the unplug fix, the box **hard-reset** during its first sustained
~90 W load (a 252k-token cold prefill): journal cut mid-stream, no OOM, no thermal
event, no clean shutdown. Same fault family as the clamp — flaky power delivery, where
a sustained full-power draw collapses the rail. Until the firmware update below, any
sustained ~90 W load risked crashing the machine.

---

## 3. The fix: update all firmware

Bringing every updatable component to latest via **`fwupdmgr`** (LVFS) resolved both
the clamp and the power-offs. The **USB-C PD controller** update targets the suspected
root cause directly; the EC governs platform power sequencing.

| component | before → after |
|---|---|
| Embedded Controller | `0x02004e18` → `0x03000508` (two majors) |
| SoC / UEFI (incl. GPU) | `0x0200941a` → `0x02009b0b` |
| USB-C PD Controller | `0x00000507` → `0x00000516` |
| kernel | 6.17.0-1018 → 6.17.0-1029 |

```bash
fwupdmgr refresh && fwupdmgr get-updates && sudo fwupdmgr update   # capsule-on-disk; reboots
```
Stay on wall power throughout. If the update process itself crashes the box, do the
full unplug ritual before retrying (crashes are what corrupt PD state).

**Post-update, verified:** burn test **100.6 TFLOPS** at 2197 MHz / 91 W, no clamp — and
the box **survived the exact 245-second sustained-90 W load that hard-reset it before**,
with no power-off. One clean pass isn't lifetime proof, but it's the first survival of
that load. (Community caveat: some firmware updates have regressed ConnectX-7 NIC
throughput — worth a post-update check if you rely on the NIC.)

Sources: [forum thread 370304](https://forums.developer.nvidia.com/t/-/370304),
[dredyson.com PD-controller analysis](https://dredyson.com/), LVFS via `fwupdmgr`.

---

## 4. Thermals — historical measurements

**November fresh-install update:** both fan RPM sensors are now readable;
sustained workloads reached higher ACPI-zone temperatures than the historical
measurements below. See [current fan and firmware observations](FAN-OBSERVATIONS-20261102.txt).
The following measurements describe the earlier installation.

Sampled across load states (GPU rail power, GPU temp, SM clock):

| state | power | GPU temp | SM clock |
|---|---|---|---|
| idle | ~5 W | 39–42 °C | 208 MHz |
| sustained decode | ~51 W | 67–68 °C | 2476 MHz |
| full burn / heavy prefill | ~91 W | 69–70 °C | ~2200 MHz |

Temperature **saturates ~70 °C** — going 51 W → 91 W adds barely 2 °C, because the EC
ramps the blower to hold a setpoint. `T.Limit` shows ~22 °C of real headroom; the thermal-
slowdown counter stays zero. **This box is thermally over-provisioned, not thermally
limited** — which is why the crashes were electrical, not heat. (During the clamp bug the
55 °C `T.Limit` reading was *fake* — a PD-fault symptom, not real thermal data.)

The fan is closed-loop controlled by the Embedded Controller with **no host interface** —
`nvidia-smi` reports fan speed `N/A`, there are no `hwmon` `pwm*`/`fan*` nodes, and no BMC.
Nothing to tune; observe it indirectly through that flat 70 °C ceiling. Hottest sensors
under load are two ACPI zones ~76 °C (the SoC/CPU side, warmer than the GPU rail), NVMe
~52 °C, WiFi ~57 °C — all in range.

**Power spec** (so you don't misread `nvidia-smi`): GB10 SoC TDP is **140 W** (CPU+GPU),
system peak **240 W** via USB-C PD. `nvidia-smi` reports only the **GPU rail** — 78–93 W
readings are in spec, not over. (An early wrong assumption was a 60 W cap; 60 W actually
matches the PD *fallback-failure* profile, not the real limit.)

---

## 5. Unified-memory crash behavior (platform-level)

The 121 GiB pool is shared by CPU and GPU, so an over-commit has **no separate VRAM to
fail into** — it starves the host, and the kernel OOM-killer fires or the box hard-hangs.
Two real incidents: two large model servers colliding on the pool (hard hang, required
power cycle), and a heavyweight quant loading while JIT-compiling kernels (host OOM →
reboot). The operational rules that follow — hard container memory caps, one GPU tenant
at a time, safe restart policies — are in [../docs/OPERATIONS.md](../docs/OPERATIONS.md),
since they're about *how you run workloads* on top of this hardware.

Other platform gotchas:
- `nvidia-smi` reports `memory.used = N/A` on GB10 — monitor `free -h` and
  `--query-compute-apps` instead.
- `qemu` binfmt registration for running amd64 containers does **not** survive reboot —
  reinstall (`docker run --privileged --rm tonistiigi/binfmt --install amd64`) after each boot.
- `sudo` requires a password here; privileged steps (firmware, poweroff) are manual.
