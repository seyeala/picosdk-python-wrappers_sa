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
print(
    f"Loaded config from {config_path}: channel={cfg['channel']}, timebase={cfg['timebase']}"
)

status = {}
chandle = ctypes.c_int16()

# Open device
status["openunit"] = ps.ps5000aOpenUnit(ctypes.byref(chandle), None, 1)
assert_pico_ok(status["openunit"])
print(f"Opened unit with handle {chandle.value}")

# Channel configuration
channel = ps.PS5000A_CHANNEL[cfg["channel"]]
coupling = ps.PS5000A_COUPLING[cfg["coupling"]]
vrange = ps.PS5000A_RANGE[cfg["vrange"]]
status["setChA"] = ps.ps5000aSetChannel(
    chandle, channel, 1, coupling, vrange, ctypes.c_float(cfg["offset_v"])
)
assert_pico_ok(status["setChA"])
print(
    "Channel configured: "
    f"channel={cfg['channel']} coupling={cfg['coupling']} vrange={cfg['vrange']} offset_v={cfg['offset_v']}"
)

# Query ADC limits
max_adc = ctypes.c_int16()
ps.ps5000aMaximumValue(chandle, ctypes.byref(max_adc))

# Trigger configuration
source = ps.PS5000A_CHANNEL[cfg["trig_source"]]
threshold = int(mV2adc(cfg["trig_level_mV"], vrange, max_adc))
direction = ps.PS5000A_THRESHOLD_DIRECTION[cfg["trig_direction"]]
status["trigger"] = ps.ps5000aSetSimpleTrigger(
    chandle, 1, source, threshold, direction, cfg["trig_delay_samples"], cfg["auto_trig_ms"]
)
assert_pico_ok(status["trigger"])
print(
    "Trigger configured: "
    f"source={cfg['trig_source']} threshold_mV={cfg['trig_level_mV']} "
    f"direction={cfg['trig_direction']} delay_samples={cfg['trig_delay_samples']} "
    f"auto_ms={cfg['auto_trig_ms']}"
)

# Sample counts
pre = int(cfg["samples"] * cfg["pre_ratio"])
post = cfg["samples"] - pre

# Timebase info
time_interval = ctypes.c_double()
returned = ctypes.c_int32()
ps.ps5000aGetTimebase2(
    chandle, cfg["timebase"], cfg["samples"],
    ctypes.byref(time_interval), ctypes.byref(returned), 0
)
print(
    f"Timebase info: time_interval={time_interval.value} returned={returned.value}"
)

# Start capture and processing
try:
    ps.ps5000aRunBlock(chandle, pre, post, cfg["timebase"], None, 0, None, None)
    print("Capture started, waiting for device to become ready...")

    # Wait until ready
    ready = ctypes.c_int16(0)
    while not ready.value:
        ps.ps5000aIsReady(chandle, ctypes.byref(ready))
        print(".", end="", flush=True)
        time.sleep(0.01)
    print()  # newline after heartbeat

    # Set buffer and retrieve data
    buffer = (ctypes.c_int16 * cfg["samples"])()
    ps.ps5000aSetDataBuffer(chandle, channel, ctypes.byref(buffer), cfg["samples"], 0, 0)

    c_samples = ctypes.c_uint32(cfg["samples"])
    overflow = ctypes.c_int16()
    ps.ps5000aGetValues(chandle, 0, ctypes.byref(c_samples), 0, 0, 0, ctypes.byref(overflow))
    print(
        f"Retrieved {c_samples.value} samples; overflow={overflow.value}"
    )
    if overflow.value:
        raise RuntimeError(f"Overflow detected: {overflow.value}")

    # Convert to physical units
    adc_mv = adc2mV(buffer, vrange, max_adc)
    time_ns = np.linspace(-pre, post - 1, cfg["samples"]) * time_interval.value

    # Store CSV in chunks
    chunk = cfg["write_chunk"]
    with open(cfg["csv_path"], "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time_ns", "mV"])
        for i in range(0, cfg["samples"], chunk):
            for t, v in zip(time_ns[i:i+chunk], adc_mv[i:i+chunk]):
                writer.writerow([t, v])
    print(
        f"Capture complete: wrote {cfg['samples']} samples to {cfg['csv_path']}"
    )
finally:
    # Ensure device is stopped and released
    ps.ps5000aStop(chandle)
    ps.ps5000aCloseUnit(chandle)
