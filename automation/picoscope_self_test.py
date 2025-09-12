import ctypes
from typing import List

# No code edits needed if you've set up the .pth hook earlier.
# Otherwise, uncomment the next two lines and point to your SDK lib dir.
# import os
# os.add_dll_directory(r"C:\Program Files\Pico Technology\SDK\lib")

from picosdk.functions import assert_pico_ok
from picosdk.constants import PICO_INFO

def get_str(buf: ctypes.Array) -> str:
    # Strip trailing NULs and decode
    raw = bytes((ctypes.c_char * len(buf)).from_buffer(buf)).split(b"\x00", 1)[0]
    try:
        return raw.decode("utf-8", "ignore")
    except Exception:
        return raw.decode(errors="ignore")

def try_open_5000a():
    from picosdk.ps5000a import ps5000a as ps
    ch = ctypes.c_int16()
    st = ps.ps5000aOpenUnit(ctypes.byref(ch), None)
    assert_pico_ok(st)
    return ps, ch

def try_open_5000():
    from picosdk.ps5000 import ps5000 as ps
    ch = ctypes.c_int16()
    st = ps.ps5000OpenUnit(ctypes.byref(ch))
    assert_pico_ok(st)
    return ps, ch

def get_unit_info(ps, ch, a_family: bool, info_key: str) -> str:
    # Map PICO_INFO name to code
    info_code = PICO_INFO[info_key]
    # Different prototypes take different integer widths for string length;
    # use a generous buffer and let driver fill it.
    buf = (ctypes.c_int8 * 256)()
    if a_family:
        req = ctypes.c_int16()
        st = ps.ps5000aGetUnitInfo(ch, buf, ctypes.c_int16(len(buf)), ctypes.byref(req), info_code)
    else:
        req = ctypes.c_int16()
        st = ps.ps5000GetUnitInfo(ch, buf, ctypes.c_int16(len(buf)), ctypes.byref(req), info_code)
    assert_pico_ok(st)
    return get_str(buf)

def list_supported_resolutions(ps, ch) -> List[str]:
    """5000A/D FlexRes only; try setting each resolution and record which succeed."""
    if not hasattr(ps, "PS5000A_DEVICE_RESOLUTION"):
        return []  # non-A models: fixed resolution
    res_names = [
        "PS5000A_DR_8BIT",
        "PS5000A_DR_12BIT",
        "PS5000A_DR_14BIT",
        "PS5000A_DR_15BIT",
        "PS5000A_DR_16BIT",
    ]
    ok = []
    for name in res_names:
        if name not in ps.PS5000A_DEVICE_RESOLUTION:
            continue
        code = ps.PS5000A_DEVICE_RESOLUTION[name]
        st = ps.ps5000aSetDeviceResolution(ch, code)
        if st == 0:  # PICO_OK
            ok.append(name.replace("PS5000A_DR_", ""))
    # Set back to 8-bit if supported
    if "PS5000A_DR_8BIT" in ps.PS5000A_DEVICE_RESOLUTION:
        ps.ps5000aSetDeviceResolution(ch, ps.PS5000A_DEVICE_RESOLUTION["PS5000A_DR_8BIT"])
    return ok

def list_supported_ranges(ps, ch, a_family: bool, channel_name: str) -> List[str]:
    """
    Probe which input ranges are accepted by asking for analogue offset limits.
    If the call returns OK for a range, we consider it supported.
    """
    supported = []
    if a_family:
        channel = ps.PS5000A_CHANNEL[channel_name]
        get_offset = ps.ps5000aGetAnalogueOffset
        rngs = ps.PS5000A_RANGE
    else:
        channel = ps.PS5000_CHANNEL[channel_name]
        get_offset = ps.ps5000GetAnalogueOffset
        rngs = ps.PS5000_RANGE

    min_off = ctypes.c_float()
    max_off = ctypes.c_float()

    for rng_name, rng_code in sorted(rngs.items(), key=lambda kv: kv[1]):
        st = get_offset(ch, channel, rng_code, ctypes.byref(min_off), ctypes.byref(max_off))
        if st == 0:  # PICO_OK
            supported.append(rng_name.replace("PS5000A_", "").replace("PS5000_", ""))
    return supported

def set_one_channel_only(ps, ch, a_family: bool, channel_name="CHANNEL_A", rng_name="5V"):
    """Enable CH A only; disable the rest so timebase queries reflect single-channel conditions."""
    if a_family:
        ch_map = ps.PS5000A_CHANNEL
        range_map = ps.PS5000A_RANGE
        set_ch = ps.ps5000aSetChannel
        coupling = ps.PS5000A_COUPLING["PS5000A_DC"]
        key_prefix = "PS5000A_CHANNEL_"
    else:
        ch_map = ps.PS5000_CHANNEL
        range_map = ps.PS5000_RANGE
        set_ch = ps.ps5000SetChannel
        coupling = 1  # DC for non-A API
        key_prefix = "PS5000_CHANNEL_"

    # Enable A
    a_key = f"{key_prefix}A"
    r_key = f"PS5000A_{rng_name}" if a_family else f"PS5000_{rng_name}"
    st = set_ch(ch, ch_map[a_key], 1, coupling, range_map[r_key], 0.0 if a_family else 0)
    assert_pico_ok(st)

    # Disable B/C/D if present
    for suffix in ("B", "C", "D"):
        key = f"{key_prefix}{suffix}"
        if key in ch_map:
            set_ch(ch, ch_map[key], 0, coupling, range_map[r_key], 0.0 if a_family else 0)

def fastest_dt_ns(ps, ch, a_family: bool, samples=1024) -> float:
    """
    Find the smallest sampling interval (ns) the driver will allow for the current
    channel/resolution configuration, by scanning timebase upward until PICO_OK.
    """
    timebase = 0
    max_iters = 10000
    if a_family:
        get_tb = ps.ps5000aGetTimebase2
        dt = ctypes.c_float()
        retmax = ctypes.c_uint32()
    else:
        get_tb = ps.ps5000GetTimebase
        dt = ctypes.c_float()
        retmax = ctypes.c_int32()

    for _ in range(max_iters):
        st = get_tb(ch, timebase, samples, ctypes.byref(dt), 1, ctypes.byref(retmax), 0)
        if st == 0:  # PICO_OK
            return float(dt.value)
        timebase += 1
    return float("nan")

def main():
    # Only non-A family
    ps, ch = try_open_5000()
    a_family = False
    print("✅ Non-A 5000 device opened. Handle:", ch.value)

   try:
        variant = get_unit_info(ps, ch, a_family, "PICO_VARIANT_INFO")   # model
    except Exception:
        variant = "(unknown)"
    try:
        serial = get_unit_info(ps, ch, a_family, "PICO_BATCH_AND_SERIAL")
    except Exception:
        serial = "(unknown)"
    try:
        drv_ver = get_unit_info(ps, ch, a_family, "PICO_DRIVER_VERSION")
    except Exception:
        drv_ver = "(unknown)"
    try:
        fw1 = get_unit_info(ps, ch, a_family, "PICO_FIRMWARE_VERSION_1")
    except Exception:
        fw1 = "(n/a)"
    try:
        fw2 = get_unit_info(ps, ch, a_family, "PICO_FIRMWARE_VERSION_2")
    except Exception:
        fw2 = "(n/a)"
    try:
        usb = get_unit_info(ps, ch, a_family, "PICO_USB_VERSION")
    except Exception:
        usb = "(unknown)"
    try:
        cal = get_unit_info(ps, ch, a_family, "PICO_CAL_DATE")
    except Exception:
        cal = "(unknown)"

    print("────────────────────────────────────")
    print(f"Model / Variant   : {variant}")
    print(f"Serial            : {serial}")
    print(f"Driver version    : {drv_ver}")
    print(f"Firmware 1 / 2    : {fw1} / {fw2}")
    print(f"USB version       : {usb}")
    print(f"Calibration date  : {cal}")
    print(f"API family        : {'ps5000a' if a_family else 'ps5000'}")
    print("────────────────────────────────────")

    # 2) Resolutions (FlexRes)
    if a_family and hasattr(ps, "PS5000A_DEVICE_RESOLUTION"):
        supported_res = list_supported_resolutions(ps, ch)
        print("Supported ADC resolutions:", ", ".join(supported_res) if supported_res else "(not reported)")
        # Default back to 8-bit for fastest sampling
        if "PS5000A_DR_8BIT" in ps.PS5000A_DEVICE_RESOLUTION:
            ps.ps5000aSetDeviceResolution(ch, ps.PS5000A_DEVICE_RESOLUTION["PS5000A_DR_8BIT"])
    else:
        print("Supported ADC resolutions: (fixed by hardware; non‑A family)")

    # 3) Ranges on Channel A (validated via analogue offset query)
    try:
        ranges = list_supported_ranges(ps, ch, a_family, "PS5000A_CHANNEL_A" if a_family else "PS5000_CHANNEL_A")
        print("Supported input ranges (A):", ", ".join(ranges) if ranges else "(not reported)")
    except Exception as e:
        print("Supported input ranges (A): (could not query)", e)

    # 4) Max samples per segment (deep memory)
    try:
        if a_family:
            max_per_seg = ctypes.c_uint32()
            st = ps.ps5000aMemorySegments(ch, 1, ctypes.byref(max_per_seg))
            assert_pico_ok(st)
            print(f"Max samples per segment (current setup): {max_per_seg.value:,}")
        else:
            max_per_seg = ctypes.c_int32()
            st = ps.ps5000MemorySegments(ch, 1, ctypes.byref(max_per_seg))
            assert_pico_ok(st)
            print(f"Max samples per segment (current setup): {max_per_seg.value:,}")
    except Exception as e:
        print("Max samples per segment: (could not query)", e)

    # 5) Fastest Δt (ns) for simple one-channel, DC, ±5 V
    try:
        set_one_channel_only(ps, ch, a_family, rng_name="5V")
        dt_ns = fastest_dt_ns(ps, ch, a_family, samples=1024)
        if dt_ns == dt_ns:  # not NaN
            print(f"Fastest achievable sampling interval (approx): {dt_ns:.3f} ns (1 ch, DC, ±5 V)")
        else:
            print("Fastest achievable sampling interval: (not found within scan)")
    except Exception as e:
        print("Fastest achievable sampling interval: (could not query)", e)

    # Close device
    try:
        if a_family:
            assert_pico_ok(ps.ps5000aCloseUnit(ch))
        else:
            assert_pico_ok(ps.ps5000CloseUnit(ch))
    finally:
        print("✅ Self‑test complete.")

if __name__ == "__main__":
    main()
