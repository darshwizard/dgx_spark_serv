#!/usr/bin/env python3
"""Thermal override regression: default90, explicitly selected95; RAM guards unchanged."""
import runpy
from pathlib import Path
ns=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/campaign_guard.py'))
f=ns['decision'];mem=10*1024**3
assert f(mem,[89.9]*7) is None
assert f(mem,[90]*7)=='thermal_limit_90C'
assert f(mem,[94.9]*7,thermal_stop_c=95) is None
assert f(mem,[95]*7,thermal_stop_c=95)=='thermal_limit_95C'
assert f(mem,[40]*6+[95],thermal_stop_c=95)=='thermal_limit_95C'
assert f(1024**3,[40]*7,thermal_stop_c=95)=='host_available_below_2GiB'
assert f(5*1024**3,[40]*7,30,95)=='available_below_6GiB_for_30s'
assert f(mem,[40]*6,thermal_stop_c=95)=='required_sensor_missing'
try:f(mem,[40]*7,thermal_stop_c=100)
except ValueError:pass
else:raise AssertionError('Unexpected thermal override accepted')
print('PASS:95C opt-in,90C default,all7 sensors and memory guards retained')
