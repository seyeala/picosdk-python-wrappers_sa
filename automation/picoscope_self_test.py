# pico_5544D_self_test.py — PicoScope 5000D (ps5000a API) self-test

import ctypes
from picosdk.ps5000a import ps5000a as ps
from picosdk.functions import assert_pico_ok
from picosdk.constants import PICO_INFO

# If you didn't set the .pth hook, uncomment:
# import os
# os.add_dll_directory(r"C:\Program Files\Pico Technology\SDK\lib")

def status_name(code: int) -> str:
    """Map numeric status code to name if present in this wrapper."""
    for k, v in ps.PICO_STATUS.items():
        if v == code:
            return k
    return f"(unknown:{code})"

def open_5544D() -> ctypes.c_int16:
    """Open with explicit resolution; give helpful messages for common errors."""
    handle = ctypes.c_int16()
    res = ps.PS5000A_DEVICE_RESOLUTION["PS5000A_DR_8BIT"]
    st = ps.ps5000aOpenUnit(ctypes.byref(handle), None, res)

    if st == ps.PICO_STATUS.get("PICO_OK", 0):
        return handle

    name = status_name(st)
    if name == "PICO_USB3_0_DEVICE_NON_USB3_0_PORT":
        raise SystemExit("USB3 device on a non-USB3 port: move the 5544D to a true USB 3.x port (rear I/O) with a SuperSpeed cable.")
    # Generic guidance for other failures (device busy, in use, not found, etc.)
    raise SystemExit(f"ps5000aOpenUnit failed: {name}. Ensure PicoScope app is closed, use a rear USB3 port/cable, and try again.")

def unit_info(handle) -> dict:
    """Query identity strings using a proper C char buffer."""
    info = {}
    need = ctypes.c_int16()
    def q(key: str) -> str:
        buf = ctypes.create_string_buffer(256)
        code = PICO_INFO[key]
        st = ps.ps5000aGetUnitInfo(
            handle,
            buf,
            ctypes.c_int16(ctypes.sizeof(buf)),
            ctypes.byref(need),
            code,
        )
        assert_pico_ok(st)
        return buf.value.decode(errors="ignore")
    info["model"]  = q("PICO_VARIANT_INFO")
    info["serial"] = q("PICO_BATCH_AND_SERIAL")
    info["driver"] = q("PICO_DRIVER_VERSION")
    info["fw1"]    = q("PICO_FIRMWARE_VERSION_1")
    info["fw2"]    = q("PICO_FIRMWARE_VERSION_2")
    info["usb"]    = q("PICO_USB_VERSION")
    info["cal"]    = q("PICO_CAL_DATE")
    return info

def list_resolutions(handle):
    """Probe FlexRes modes the unit accepts."""
    names = ["PS5000A_DR_8BIT","PS5000A_DR_12BIT","PS5000A_DR_14BIT","PS5000A_DR_15BIT","PS5000A_DR_16BIT"]
    ok = []
    for n in names:
        code = ps.PS5000A_DEVICE_RESOLUTION.get(n)
        if code is None:
            continue
        st = ps.ps5000aSetDeviceResolution(handle, code)
        if st == ps.PICO_STATUS.get("PICO_OK", 0):
            ok.append(n.replace("PS5000A_DR_", ""))
    # Restore 8-bit for timing/memory queries
    ps.ps5000aSetDeviceResolution(handle, ps.PS5000A_DEVICE_RESOLUTION["PS5000A_DR_8BIT"])
    return ok

def list_ranges_A(handle):
    """List input ranges on Channel A by querying analogue offset limits."""
    ranges = []
    chA = ps.PS5000A_CHANNEL["PS5000A_CHANNEL_A"]
    min_off = ctypes.c_float()
    max_off = ctypes.c_float()
    for name, code in sorted(ps.PS5000A_RANGE.items(), key=lambda kv: kv[1]):
        st = ps.ps5000aGetAnalogueOffset(handle, chA, code, ctypes.byref(min_off), ctypes.byref(max_off))
        if st == ps.PICO_STATUS.get("PICO_OK", 0):
            ranges.append(name.replace("PS5000A_", ""))  # e.g., 10MV ... 50V
    return ranges

def set_one_channel_A_5V(handle):
    """Enable CH A only; disable others (single-channel best case for Δt)."""
    coupling = ps.PS5000A_COUPLING["PS5000A_DC"]
    rng = ps.PS5000A_RANGE["PS5000A_5V"]
    assert_pico_ok(ps.ps5000aSetChannel(handle, ps.PS5000A_CHANNEL["PS5000A_CHANNEL_A"], 1, coupling, rng, 0.0))
    for key in ("PS5000A_CHANNEL_B","PS5000A_CHANNEL_C","PS5000A_CHANNEL_D"):
        if key in ps.PS5000A_CHANNEL:
            ps.ps5000aSetChannel(handle, ps.PS5000A_CHANNEL[key], 0, coupling, rng, 0.0)

def fastest_dt_ns(handle, samples=1024):
    """Scan timebase upward to find minimum Δt (ns) for current config."""
    tb = 0
    dt_ns = ctypes.c_float()
    retmax = ctypes.c_uint32()
    while tb < 10000:
        st = ps.ps5000aGetTimebase2(handle, tb, samples, ctypes.byref(dt_ns), 1, ctypes.byref(retmax), 0)
        if st == ps.PICO_STATUS.get("PICO_OK", 0):
            return float(dt_ns.value), tb
        tb += 1
    return float("nan"), -1

def max_samples_per_segment(handle):
    """Deep memory per segment for current config."""
    max_per_seg = ctypes.c_uint32()
    assert_pico_ok(ps.ps5000aMemorySegments(handle, 1, ctypes.byref(max_per_seg)))
    return max_per_seg.value

def main():
    handle = open_5544D()
    try:
        info = unit_info(handle)
        print("✅ Opened PicoScope 5000D (ps5000a). Handle:", handle.value)
        print("────────────────────────────────────")
        for k in ("model","serial","driver","fw1","fw2","usb","cal"):
            print(f"{k:>12}: {info.get(k,'')}")
        print("────────────────────────────────────")

        res_ok = list_resolutions(handle)
        print("ADC resolutions supported:", ", ".join(res_ok) if res_ok else "(not reported)")

        ranges = list_ranges_A(handle)
        print("Channel A input ranges:", ", ".join(ranges) if ranges else "(not reported)")

        set_one_channel_A_5V(handle)
        dt, tb = fastest_dt_ns(handle, samples=1024)
        if dt == dt:
            print(f"Fastest Δt (approx): {dt:.3f} ns  (timebase={tb})")
        else:
            print("Fastest Δt (approx): (not found in scan)")

        print(f"Max samples per segment (current setup): {max_samples_per_segment(handle):,}")

    finally:
        assert_pico_ok(ps.ps5000aCloseUnit(handle))
        print("✅ Self-test complete.")

if __name__ == "__main__":
    main()
