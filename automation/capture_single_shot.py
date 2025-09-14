# -*- coding: utf-8 -*-
# capture_single_shot.py — PS5000A block capture with CSV/NumPy outputs
# Reads settings from YAML and allows command-line overrides
#
# Enhancements:
# - If available, import daqio.publisher and append a compact suffix derived
#   from the latest AI/AO publication to the timestamped file name.
# - If daqio/publishers are unavailable or no payload has been published yet,
#   print an info message and proceed with the original naming.

import argparse
import ctypes
import time
import csv
import os
import re
import hashlib
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

import numpy as np
import yaml
from picosdk.ps5000a import ps5000a as ps
from picosdk.functions import assert_pico_ok, adc2mV, mV2adc

CFG_PATH = "capture_config_test.yml"

# ---- Optional integration with daqio.publisher (same-process latest snapshot) ----
try:
    from daqio.publisher import get_latest_ai as _get_latest_ai, get_latest_ao as _get_latest_ao  # type: ignore
    _DAQIO_AVAILABLE = True
except Exception:
    _get_latest_ai = None  # type: ignore[assignment]
    _get_latest_ao = None  # type: ignore[assignment]
    _DAQIO_AVAILABLE = False

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(s: str) -> str:
    """Make a string filename-safe (single path component)."""
    return _SAFE.sub("-", str(s)).strip("-")


def _short_ch(ch: str) -> str:
    """Shorten channel name like 'Dev1/ai0' -> 'ai0'."""
    return ch.split("/")[-1] if "/" in ch else ch


def _fmt_val(v: float, ndigits: int = 3) -> str:
    """Format a float compactly for filenames, e.g., -0.0123 -> 'm0p012'."""
    s = f"{float(v):.{ndigits}f}"
    return s.replace("-", "m").replace(".", "p")


def _build_name_suffix(
    payload: Optional[Dict[str, Any]],
    *,
    mode: str = "mini",     # 'none' | 'mini' | 'full'
    max_len: int = 120
) -> Tuple[str, Dict[str, Any]]:
    """
    Turn a DAQ payload into a short, filename-safe suffix.
    Returns (suffix, meta). If no payload, returns ("", {}).
    """
    if not payload or mode == "none":
        return "", {}

    # Accept either AO ('channel_values') or AI ('results') schema
    values = payload.get("channel_values") or payload.get("results")
    if not isinstance(values, dict):
        # Unknown shape → safe hash
        raw = repr(payload).encode()
        h = hashlib.sha1(raw).hexdigest()[:8]
        return f"DAQ_{h}", {"daq_payload": payload}

    items = sorted(values.items())  # deterministic order
    if mode == "mini":
        items = items[:2]  # keep it short

    parts = []
    if "timestamp" in payload:
        parts.append(_slug(payload["timestamp"]))
    parts.extend(f"{_slug(_short_ch(ch))}_{_fmt_val(val)}" for ch, val in items)

    suffix = "__".join(parts)
    meta = {"daq_payload": payload, "daq_values": items}

    # Cap length of the suffix to keep filename components safe on all platforms
    if len(suffix) > max_len:
        h = hashlib.sha1(suffix.encode()).hexdigest()[:8]
        # leave some room for the hash
        keep = max(0, max_len - (2 + len(h)))
        suffix = f"{suffix[:keep]}__{h}"

    return suffix, meta


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
    # Optional naming controls (kept purely optional; defaults below preserve behavior)
    p.add_argument("--daq-source", choices=["auto", "ai", "ao", "none"], help="Which DAQ snapshot to embed in name")
    p.add_argument("--name-embed", choices=["none", "mini", "full"], help="How much DAQ info to embed")
    p.add_argument("--name-maxlen", type=int, help="Cap length of the DAQ suffix")
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

    # ---- Build timestamp (original behavior) ----
    ts_str = ""
    now = None
    if cfg.get("timestamp_filenames", False):
        now = datetime.now()
        ts_str = (
            f"M{now.month:02d}-D{now.day:02d}-H{now.hour:02d}-"
            f"M{now.minute:02d}-S{now.second:02d}-U.{now.microsecond // 1000:03d}"
        )

    # ---- Optionally fold latest DAQ snapshot into the name (safe fallback) ----
    # Defaults that keep behavior if cfg keys absent
    daq_source = str(cfg.get("daq_source", "auto")).lower()      # auto | ai | ao | none
    name_embed = str(cfg.get("name_embed", "mini")).lower()      # none | mini | full
    name_max   = int(cfg.get("name_maxlen", 120))

    name_stem = ts_str or "capture"

    if cfg.get("timestamp_filenames", False) and name_embed != "none":
        if not _DAQIO_AVAILABLE:
            print("[info] daqio.publisher not found; proceeding without DAQ suffix.")
        else:
            # choose payload based on source preference
            payload = None
            if daq_source in ("auto", "ai") and _get_latest_ai is not None:
                try:
                    payload = _get_latest_ai()
                except Exception:
                    payload = None
            if payload is None and daq_source in ("auto", "ao") and _get_latest_ao is not None:
                try:
                    payload = _get_latest_ao()
                except Exception:
                    payload = None

            if payload:
                suffix, _meta = _build_name_suffix(payload, mode=name_embed, max_len=name_max)
                if suffix:
                    name_stem = f"{name_stem}__{suffix}"
            else:
                # No recent publication available at this moment
                print("[info] No latest DAQ payload available; proceeding without DAQ suffix.")

    # ---- Run block ----
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
            csv_dir = os.path.dirname(csv_path) or "."
            csv_path = os.path.join(csv_dir, f"{name_stem}.csv")
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
            np_dir = os.path.dirname(np_path) or "."
            np_path = os.path.join(np_dir, f"{name_stem}.npz")
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
