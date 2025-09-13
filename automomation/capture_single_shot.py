# -*- coding: utf-8 -*-
# capture_single_shot.py — PS5000A one-shot, single-channel, immediate capture

import ctypes
import time
import csv
import yaml
import numpy as np
from picosdk.ps5000a import ps5000a as ps
from picosdk.functions import assert_pico_ok, adc2mV, mV2adc

CFG_PATH = "capture_config_test.yml"

# If you didn't set the .pth hook earlier, you could uncomment:
# import os
# os.add_dll_directory(r"C:\Program Files\Pico Technology\SDK\lib")

# ---- Load config ----
with open(CFG_PATH, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

print(f"Loaded config: channel={cfg['channel']} timebase={cfg['timebase']} samples={cfg['samples']}")

# ---- Open unit at requested resolution (8-bit is fastest) ----
h = ctypes.c_int16()
res = ps.PS5000A_DEVICE_RESOLUTION[cfg.get("resolution", "PS5000A_DR_8BIT")]
st = ps.ps5000aOpenUnit(ctypes.byref(h), None, res)

# Handle USB power-source prompts (same as Pico example)
try:
    assert_pico_ok(st)
except Exception:
    if st in (
        ps.PICO_STATUS.get("PICO_POWER_SUPPLY_NOT_CONNECTED", 282),
        ps.PICO_STATUS.get("PICO_USB3_0_DEVICE_NON_USB3_0_PORT", 286),
    ):
        assert_pico_ok(ps.ps5000aChangePowerSource(h, st))
    else:
        raise

print(f"Opened PS5000A handle: {h.value}")

try:
    # ---- Channel A: enable, DC, ±5 V, 0 offset ----
    chan = ps.PS5000A_CHANNEL[cfg["channel"]]
    coup = ps.PS5000A_COUPLING[cfg["coupling"]]
    vrng = ps.PS5000A_RANGE[cfg["vrange"]]
    assert_pico_ok(ps.ps5000aSetChannel(h, chan, 1, coup, vrng, ctypes.c_float(cfg["offset_v"])))
    print("Channel A set.")

    # ---- Max ADC ----
    max_adc = ctypes.c_int16()
    assert_pico_ok(ps.ps5000aMaximumValue(h, ctypes.byref(max_adc)))

    # ---- Trigger (disabled => immediate) ----
    if cfg.get("trig_enabled", False):
        src  = ps.PS5000A_CHANNEL[cfg["trig_source"]]
        tdir = ps.PS5000A_THRESHOLD_DIRECTION[cfg["trig_direction"]]
        thr  = int(mV2adc(cfg["trig_level_mV"], vrng, max_adc))
        assert_pico_ok(ps.ps5000aSetSimpleTrigger(
            h, 1, src, thr, tdir,
            int(cfg["trig_delay_samples"]),
            int(cfg["auto_trig_ms"])
        ))
        print("Trigger enabled.")
    else:
        assert_pico_ok(ps.ps5000aSetSimpleTrigger(
            h, 0, chan, 0,
            ps.PS5000A_THRESHOLD_DIRECTION["PS5000A_RISING"],
            0, 0
        ))
        print("Trigger disabled (immediate).")

    # ---- Sample counts ----
    total = int(cfg["samples"])
    pre   = int(total * float(cfg["pre_ratio"]))
    post  = total - pre

    # ---- Timebase: ps5000aGetTimebase2 (6 arguments) ----
    timeIntervalns = ctypes.c_float()
    returnedMax    = ctypes.c_int32()
    # (handle, timebase, noSamples, &dt, &returnedMax, segmentIndex)
    assert_pico_ok(ps.ps5000aGetTimebase2(
        h, int(cfg["timebase"]), total,
        ctypes.byref(timeIntervalns),
        ctypes.byref(returnedMax),
        0
    ))
    dt_ns = float(timeIntervalns.value)
    print(f"Timebase OK: dt ~ {dt_ns:.3f} ns, driver maxSamples={returnedMax.value}")

    # ---- Run block ----
    # (handle, pre, post, timebase, timeIndisposedMs*, segmentIndex, lpReady, pParameter)
    assert_pico_ok(ps.ps5000aRunBlock(h, pre, post, int(cfg["timebase"]), None, 0, None, None))
    print("Acquiring...")
    ready = ctypes.c_int16(0)
    while not ready.value:
        assert_pico_ok(ps.ps5000aIsReady(h, ctypes.byref(ready)))
        time.sleep(0.005)

    # ---- Buffers (PS5000A uses SetDataBuffers with max & min) ----
    buf_max = (ctypes.c_int16 * total)()
    buf_min = (ctypes.c_int16 * total)()  # required by API even if not used
    # (handle, channel, pMax, pMin, length, segmentIndex, ratioMode=0)
    assert_pico_ok(ps.ps5000aSetDataBuffers(h, chan, ctypes.byref(buf_max), ctypes.byref(buf_min), total, 0, 0))

    # ---- Retrieve values ----
    c_samples = ctypes.c_int32(total)
    overflow  = ctypes.c_int16()
    # (handle, startIndex, &numSamples, downsampleRatio=0, ratioMode=0, seg=0, &overflow)
    assert_pico_ok(ps.ps5000aGetValues(h, 0, ctypes.byref(c_samples), 0, 0, 0, ctypes.byref(overflow)))
    ns = int(c_samples.value)
    print(f"Retrieved {ns} samples; overflow={overflow.value}")

    # ---- Convert to mV and build time (ns) ----
    mv = adc2mV(buf_max, vrng, max_adc)
    time_ns = (np.arange(ns, dtype=np.int64) - pre) * dt_ns

    # ---- Write CSV ----
    chunk = int(cfg["write_chunk"])
    with open(cfg["csv_path"], "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_ns", "mV"])
        for i in range(0, ns, chunk):
            j = min(i + chunk, ns)
            w.writerows(zip(time_ns[i:j], mv[i:j]))
    print(f"Wrote {ns} samples to {cfg['csv_path']}")

finally:
    # ---- Teardown (guarded) ----
    try:
        assert_pico_ok(ps.ps5000aStop(h))
    except Exception:
        pass
    try:
        assert_pico_ok(ps.ps5000aCloseUnit(h))
    except Exception:
        pass