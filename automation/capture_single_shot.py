import csv
import ctypes
import numpy as np
import yaml
import time
from picosdk.ps5000a import ps5000a as ps
from picosdk.functions import adc2mV, assert_pico_ok, mV2adc

# Load settings
config_path = "capture_config_test.yml"
with open(config_path) as f:
    cfg = yaml.safe_load(f)
print(f"Loaded config: channel={cfg['channel']} timebase={cfg['timebase']} samples={cfg['samples']}")

chandle = ctypes.c_int16()

# Open device at 8-bit (fastest). If you want to honor YAML resolution, map it here.
assert_pico_ok(ps.ps5000aOpenUnit(
    ctypes.byref(chandle),
    None,
    ps.PS5000A_DEVICE_RESOLUTION["PS5000A_DR_8BIT"]
))
print(f"Opened unit handle {chandle.value}")

# Channel configuration
channel  = ps.PS5000A_CHANNEL[cfg["channel"]]
coupling = ps.PS5000A_COUPLING[cfg["coupling"]]
vrange   = ps.PS5000A_RANGE[cfg["vrange"]]
assert_pico_ok(ps.ps5000aSetChannel(chandle, channel, 1, coupling, vrange, ctypes.c_float(cfg["offset_v"])))
print(f"Channel set: {cfg['channel']} {cfg['coupling']} {cfg['vrange']} offset={cfg['offset_v']}")

# Max ADC
max_adc = ctypes.c_int16()
assert_pico_ok(ps.ps5000aMaximumValue(chandle, ctypes.byref(max_adc)))

# Trigger (disable for immediate capture if trig_enabled: false)
trig_enabled = bool(cfg.get("trig_enabled", True))
if trig_enabled:
    source    = ps.PS5000A_CHANNEL[cfg["trig_source"]]
    direction = ps.PS5000A_THRESHOLD_DIRECTION[cfg["trig_direction"]]
    threshold = int(mV2adc(cfg["trig_level_mV"], vrange, max_adc))
    assert_pico_ok(ps.ps5000aSetSimpleTrigger(
        chandle, 1, source, threshold, direction, int(cfg["trig_delay_samples"]), int(cfg["auto_trig_ms"])
    ))
    print(f"Trigger: {cfg['trig_source']} {cfg['trig_direction']} {cfg['trig_level_mV']} mV, auto_ms={cfg['auto_trig_ms']}")
else:
    # enabled=0 for immediate acquisition
    assert_pico_ok(ps.ps5000aSetSimpleTrigger(
        chandle, 0, channel, 0, ps.PS5000A_THRESHOLD_DIRECTION['PS5000A_RISING'], 0, 0
    ))
    print("Trigger disabled (immediate acquisition)")

# Pre/Post sample counts
pre  = int(cfg["samples"] * float(cfg["pre_ratio"]))
post = int(cfg["samples"] - pre)

# --- Timebase info (YOUR WRAPPER = 6-arg GetTimebase2) ---
time_interval_ns = ctypes.c_float()     # float, not double
oversample       = 1
assert_pico_ok(ps.ps5000aGetTimebase2(
    chandle, int(cfg["timebase"]), int(cfg["samples"]),
    ctypes.byref(time_interval_ns), oversample, 0
))
print(f"Timebase OK: dt={time_interval_ns.value:.3f} ns")

# Arm & run (oversample=1)
assert_pico_ok(ps.ps5000aRunBlock(chandle, pre, post, int(cfg["timebase"]), oversample, None, 0, None, None))
print("Acquiring...")
ready = ctypes.c_int16(0)
while not ready.value:
    assert_pico_ok(ps.ps5000aIsReady(chandle, ctypes.byref(ready)))
    time.sleep(0.005)

# Buffer & retrieve
buffer = (ctypes.c_int16 * int(cfg["samples"]))()
assert_pico_ok(ps.ps5000aSetDataBuffer(
    chandle, channel, buffer, int(cfg["samples"]), 0,
    ps.PS5000A_RATIO_MODE['PS5000A_RATIO_MODE_RAW']
))

n_samples = ctypes.c_uint32(int(cfg["samples"]))
overflow  = ctypes.c_int16()
assert_pico_ok(ps.ps5000aGetValues(
    chandle, 0, ctypes.byref(n_samples), 1,   # downSampleRatio = 1
    ps.PS5000A_RATIO_MODE['PS5000A_RATIO_MODE_RAW'],
    0, ctypes.byref(overflow)
))
print(f"Retrieved {n_samples.value} samples; overflow={overflow.value}")
if overflow.value:
    raise RuntimeError(f"Overflow detected: {overflow.value}")

# Convert to mV and build time (ns)
mv = adc2mV(buffer, vrange, max_adc)
time_ns = np.linspace(-pre, post - 1, n_samples.value, dtype=np.float64) * float(time_interval_ns.value)

# Write CSV (chunked)
chunk = int(cfg["write_chunk"])
with open(cfg["csv_path"], "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["time_ns", "mV"])
    for i in range(0, n_samples.value, chunk):
        j = min(i + chunk, n_samples.value)
        w.writerows(zip(time_ns[i:j], mv[i:j]))
print(f"Wrote {n_samples.value} samples to {cfg['csv_path']}")

# Cleanup
assert_pico_ok(ps.ps5000aStop(chandle))
assert_pico_ok(ps.ps5000aCloseUnit(chandle))
