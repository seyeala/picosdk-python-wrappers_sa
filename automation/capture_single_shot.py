# -*- coding: utf-8 -*-
# capture_single_shot.py — PS5000A block capture with CSV/NumPy outputs
# Reads settings from YAML and allows command-line overrides

import argparse
import ctypes
import time
import csv
import os
from datetime import datetime

import numpy as np
import yaml
from picosdk.ps5000a import ps5000a as ps
from picosdk.functions import assert_pico_ok, adc2mV, mV2adc

CFG_PATH = "capture_config_test.yml"


def build_argparser() -> argparse.ArgumentParser:
    """Create an argument parser covering all YAML config options."""
    p = argparse.ArgumentParser(description="PS5000A single-shot capture")
    p.add_argument("-c", "--config", default=CFG_PATH, help="Path to YAML configuration file")
    p.add_argument("--resolution")
    p.add_argument("--channel")
    p.add_argument("--coupling")
    p.add_argument("--vrange")
    p.add_argument("--offset-v", type=float, dest="offset_v")
    p.add_argument("--timebase", type=int)
    p.add_argument("--samples", type=int)
    p.add_argument("--pre-ratio", type=float, dest="pre_ratio")
    p.add_argument("--trig-enabled", dest="trig_enabled", action="store_true")
    p.add_argument("--no-trig-enabled", dest="trig_enabled", action="store_false")
    p.add_argument("--trig-source")
    p.add_argument("--trig-level-mv", type=float, dest="trig_level_mV")
    p.add_argument("--trig-direction")
    p.add_argument("--auto-trig-ms", type=int, dest="auto_trig_ms")
    p.add_argument("--trig-delay-samples", type=int, dest="trig_delay_samples")
    p.add_argument("--save-format")
    p.add_argument("--csv-path")
    p.add_argument("--numpy-path")
    p.add_argument("--write-chunk", type=int, dest="write_chunk")
    p.add_argument("--timestamp-filenames", dest="timestamp_filenames", action="store_true")
    p.add_argument("--no-timestamp-filenames", dest="timestamp_filenames", action="store_false")
    p.set_defaults(trig_enabled=None, timestamp_filenames=None)
    return p


def apply_overrides(cfg: dict, args: argparse.Namespace) -> dict:
    """Override YAML values with any command-line flags."""
    for k, v in vars(args).items():
        if k == "config" or v is None:
            continue
        cfg[k] = v
    return cfg

def pico_ok(code: int) -> bool:
    return code == ps.PICO_STATUS["PICO_OK"]


def main(cfg: dict) -> None:
    print(f"Loaded config: channel={cfg['channel']} timebase={cfg['timebase']} samples={cfg['samples']}")

    # ---- Open unit at requested resolution ----
    h = ctypes.c_int16()
    res = ps.PS5000A_DEVICE_RESOLUTION[cfg.get("resolution", "PS5000A_DR_8BIT")]
    st = ps.ps5000aOpenUnit(ctypes.byref(h), None, res)

    # Handle common power-source prompts (same pattern as Pico examples)
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

    # ---- Channel A configuration ----
    chan = ps.PS5000A_CHANNEL[cfg["channel"]]
    coup = ps.PS5000A_COUPLING[cfg["coupling"]]
    vrng = ps.PS5000A_RANGE[cfg["vrange"]]
    assert_pico_ok(ps.ps5000aSetChannel(h, chan, 1, coup, vrng, ctypes.c_float(cfg["offset_v"])))
    print("Channel A set.")

    # Try to disable other channels to maximize sample rate (ignore INVALID_CHANNEL)
    for ch_key in ("PS5000A_CHANNEL_B", "PS5000A_CHANNEL_C", "PS5000A_CHANNEL_D"):
        if ch_key in ps.PS5000A_CHANNEL:
            st = ps.ps5000aSetChannel(h, ps.PS5000A_CHANNEL[ch_key], 0, coup, vrng, ctypes.c_float(0.0))
            if (ps.PICO_STATUS.get("PICO_INVALID_CHANNEL") is not None) and (st == ps.PICO_STATUS["PICO_INVALID_CHANNEL"]):
                pass  # not present on your variant → ignore
            else:
                assert_pico_ok(st)

    # ---- Max ADC (for conversions) ----
    max_adc = ctypes.c_int16()
    assert_pico_ok(ps.ps5000aMaximumValue(h, ctypes.byref(max_adc)))

    # ---- Trigger config ----
    if cfg.get("trig_enabled", False):
        src = ps.PS5000A_CHANNEL[cfg["trig_source"]]
        tdir = ps.PS5000A_THRESHOLD_DIRECTION[cfg["trig_direction"]]
        thr  = int(mV2adc(cfg["trig_level_mV"], vrng, max_adc))
        assert_pico_ok(ps.ps5000aSetSimpleTrigger(
            h, 1, src, thr, tdir, int(cfg["trig_delay_samples"]), int(cfg["auto_trig_ms"])
        ))
        print("Trigger enabled.")
    else:
        assert_pico_ok(ps.ps5000aSetSimpleTrigger(
            h, 0, chan, 0, ps.PS5000A_THRESHOLD_DIRECTION["PS5000A_RISING"], 0, 0
        ))
        print("Trigger disabled (immediate).")

    # ---- Sample counts ----
    total = int(cfg["samples"])
    pre   = int(total * float(cfg["pre_ratio"]))
    post  = total - pre

    # ---- Get valid timebase (6-arg ps5000aGetTimebase2) ----
    tb_req = int(cfg["timebase"])
    tb     = tb_req
    dt_ns  = ctypes.c_float()
    retmax = ctypes.c_int32()

    while True:
        st = ps.ps5000aGetTimebase2(h, tb, total, ctypes.byref(dt_ns), ctypes.byref(retmax), 0)
        if pico_ok(st):
            break
        if st == ps.PICO_STATUS.get("PICO_INVALID_TIMEBASE"):
            tb += 1
            continue
        assert_pico_ok(st)

    if tb != tb_req:
        print(f"Requested timebase={tb_req} not valid for {total} samples; using timebase={tb}")
    print(f"Timebase OK: dt ~ {dt_ns.value:.3f} ns, driver maxSamples={retmax.value}")

    # ---- Run block ----
    ts_str = ""
    if cfg.get("timestamp_filenames", False):
        now = datetime.now()
        ts_str = (
            f"M{now.month:02d}-D{now.day:02d}-H{now.hour:02d}-"
            f"M{now.minute:02d}-S{now.second:02d}-U.{now.microsecond // 1000:03d}"
        )
    assert_pico_ok(ps.ps5000aRunBlock(h, pre, post, tb, None, 0, None, None))
    print("Acquiring...")
    ready = ctypes.c_int16(0)
    while not ready.value:
        assert_pico_ok(ps.ps5000aIsReady(h, ctypes.byref(ready)))
        time.sleep(0.005)

    # ---- Buffers & acquisition (SetDataBuffers requires max & min buffers) ----
    buf_max = (ctypes.c_int16 * total)()
    buf_min = (ctypes.c_int16 * total)()   # not used for downsampling here, but required by API
    assert_pico_ok(ps.ps5000aSetDataBuffers(h, chan, ctypes.byref(buf_max), ctypes.byref(buf_min), total, 0, 0))

    c_samples = ctypes.c_int32(total)
    overflow  = ctypes.c_int16()
    assert_pico_ok(ps.ps5000aGetValues(h, 0, ctypes.byref(c_samples), 0, 0, 0, ctypes.byref(overflow)))
    ns = int(c_samples.value)
    print(f"Retrieved {ns} samples; overflow={overflow.value}")

    # ---- Convert to mV & build time axis (ns) ----
    mv = adc2mV(buf_max, vrng, max_adc)
    time_ns = (np.arange(ns, dtype=np.int64) - pre) * float(dt_ns.value)

    # ---- Output selection ----
    save_fmt = str(cfg.get("save_format", "csv")).strip().lower()
    do_csv   = save_fmt in ("csv", "both")
    do_np    = save_fmt in ("numpy", "both")

    if do_csv:
        chunk = int(cfg.get("write_chunk", 200000))
        csv_path = cfg.get("csv_path", "capture.csv")
        if cfg.get("timestamp_filenames", False):
            csv_dir = os.path.dirname(csv_path)
            csv_path = os.path.join(csv_dir, f"{ts_str}.csv")
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_ns", "mV"])
            for i in range(0, ns, chunk):
                j = min(i + chunk, ns)
                w.writerows(zip(time_ns[i:j], mv[i:j]))
        print(f"CSV: wrote {ns} rows to {csv_path}")

    if do_np:
        np_path = cfg.get("numpy_path", "capture.npz")
        if cfg.get("timestamp_filenames", False):
            np_dir = os.path.dirname(np_path)
            np_path = os.path.join(np_dir, f"{ts_str}.npz")
        # store both arrays + minimal metadata together
        np.savez(
            np_path,
            time_ns=time_ns,
            mV=np.asarray(mv, dtype=np.int16),   # stored as int16 mV to keep size small
            dt_ns=float(dt_ns.value),
            pre_samples=pre,
            total_samples=ns,
            vrange=cfg["vrange"],
            resolution=cfg.get("resolution", "PS5000A_DR_8BIT"),
        )
        print(f"NumPy: wrote arrays to {np_path}")

    # ---- Teardown ----
    assert_pico_ok(ps.ps5000aStop(h))
    assert_pico_ok(ps.ps5000aCloseUnit(h))


if __name__ == "__main__":
    parser = build_argparser()
    args = parser.parse_args()
    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)
    cfg = apply_overrides(cfg, args)
    main(cfg)

