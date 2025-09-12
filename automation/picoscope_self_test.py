# pico_5544D_self_test.py — tailored for PicoScope 5000D (ps5000a API)

import ctypes
from picosdk.functions import assert_pico_ok
from picosdk.constants import PICO_INFO
from picosdk.ps5000a import ps5000a as ps

# If you didn't set the .pth hook earlier, uncomment the next 2 lines:
# import os
# os.add_dll_directory(r"C:\Program Files\Pico Technology\SDK\lib")

def get_str(buf: ctypes.Array) -> str:
    raw = bytes((ctypes.c_char * len(buf)).from_buffer(buf)).split(b"\x00", 1)[0]
    return raw.decode(errors="ignore")

def unit_info(handle) -> dict:
    info = {}
    buf = (ctypes.c_int8 * 256)()
    need = ctypes.c_int16()
    def q(key):
        code = PICO_INFO[key]
        st = ps.ps5000aGetUnitInfo(handle, buf, ctypes.c_int16(len(buf)), ctypes.byref(need), code)
        assert_pico_ok(st)
        return get_str(buf)
    info["model"]  = q("PICO_VARIANT_INFO")
    info["serial"] = q("PICO_BATCH_AND_SERIAL")
    info["driver"] = q("PICO_DRIVER_VERSION")
    info["fw1"]    = q("PICO_FIRMWARE_VERSION_1")
    info["fw2"]    = q("PICO_FIRMWARE_VERSION_2")
    info["usb"]    = q("PICO_USB_VERSION")
    info["cal"]    = q("PICO_CAL_DATE")
    return info

def list_resolutions(handle):
    """Probe FlexRes resolutions that the unit will accept."""
    resnames = [
        "PS5000A_DR_8BIT", "PS5000A_DR_12BIT", "PS5000A_DR_14BIT",
        "PS5000A_DR_15BIT", "PS5000A_DR_16BIT",
    ]
    ok = []
    for name in resnames:
        code = ps.PS5000A_DEVICE_RESOLUTION.get(name)
        if code is None:
            continue
        st = ps.ps5000aSetDeviceResolution(handle, code)
        if st == 0:  # PICO_OK
            ok.append(name.replace("PS5000A_DR_", ""))
    # Default back to 8-bit for subsequent queries
    ps.ps5000aSetDeviceResolution(handle, ps.PS5000A_DEVICE_RESOLUTION["PS5000A_DR_8BIT"])
    return ok

def list_ranges_A(handle):
    """List voltage ranges supported on Channel A by asking analogue offset limits."""
    rngs = []
    chA = ps.PS5000A_CHANNEL["PS5000A_CHANNEL_A"]
    min_off = ctypes.c_float()
    max_off = ctypes.c_float()
    for name, code in sorted(ps.PS5000A_RANGE.items(), key=lambda kv: kv[1]):
        st = ps.ps5000aGetAnalogueOffset(handle, chA, code, ctypes.byref(min_off), ctypes.byref(max_off))
        if st == 0:
            rngs.append(name.replace("PS5000A_", ""))  # e.g., 10MV, 20MV, 50MV, 100MV ... 50V
    return rngs

def set_one_channel_A_5V(handle):
    """Enable only CH A, DC, ±5 V so timebase queries reflect single-channel best case."""
    coupling = ps.PS5000A_COUPLING["PS5000A_DC"]
    rng = ps.PS5000A_RANGE["PS5000A_5V"]
    assert_pico_ok(ps.ps5000aSetChannel(handle, ps.PS5000A_CHANNEL["PS5000A_CHANNEL_A"], 1, coupling, rng, 0.0))
    for ch_name in ("PS5000A_CHANNEL_B", "PS5000A_CHANNEL_C", "PS5000A_CHANNEL_D"):
        if ch_name in ps.PS5000A_CHANNEL:
            ps.ps5000aSetChannel(handle, ps.PS5000A_CHANNEL[ch_name], 0, coupling, rng, 0.0)

def fastest_dt_ns(handle, samples=1024):
    """Scan timebase to find the smallest Δt the driver allows for the current config."""
    timebase = 0
    dt_ns = ctypes.c_float()
    retmax = ctypes.c_uint32()
    # oversample = 1, segment index = 0
    while timebase < 10000:
        st = ps.ps5000aGetTimebase2(handle, timebase, samples, ctypes.byref(dt_ns), 1, ctypes.byref(retmax), 0)
        if st == 0:
            return float(dt_ns.value), timebase
        timebase += 1
    return float("nan"), -1

def max_samples_per_segment(handle):
    """Query deep memory per segment under current config."""
    max_per_seg = ctypes.c_uint32()
    assert_pico_ok(ps.ps5000aMemorySegments(handle, 1, ctypes.byref(max_per_seg)))
    return max_per_seg.value

def main():
    # Close the PicoScope desktop app before running this.
    # Open the unit with an explicit resolution (8-bit = fastest)
    handle = ctypes.c_int16()
    res = ps.PS5000A_DEVICE_RESOLUTION["PS5000A_DR_8BIT"]
    assert_pico_ok(ps.ps5000aOpenUnit(ctypes.byref(handle), None, res))

    try:
        info = unit_info(handle)
        print("✅ Opened 5000D (ps5000a). Handle:", handle.value)
        print("────────────────────────────────────")
        for k, v in info.items():
            print(f"{k:>12}: {v}")
        print("────────────────────────────────────")

        # Resolutions (FlexRes)
        res_ok = list_resolutions(handle)
        print("ADC resolutions supported:", ", ".join(res_ok) if res_ok else "(not reported)")

        # Channel A ranges
        rngs = list_ranges_A(handle)
        print("Channel A input ranges:", ", ".join(rngs) if rngs else "(not reported)")

        # Single-channel best case for Δt and memory
        set_one_channel_A_5V(handle)
        dt, tb = fastest_dt_ns(handle, samples=1024)
        print(f"Fastest Δt (approx): {dt:.3f} ns  (timebase={tb})")
        print(f"Max samples per segment (current setup): {max_samples_per_segment(handle):,}")

    finally:
        assert_pico_ok(ps.ps5000aCloseUnit(handle))
        print("✅ Self-test complete.")

if __name__ == "__main__":
    main()
