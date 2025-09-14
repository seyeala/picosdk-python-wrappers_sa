# -*- coding: utf-8 -*-
# capture_multi_shot.py — run repeated captures using capture_single_shot
# Reads settings from YAML and allows command-line overrides

import argparse
import sys
import time
import yaml

import capture_single_shot

try:  # Windows-only module for non-blocking key presses
    import msvcrt  # type: ignore
except Exception:  # pragma: no cover - msvcrt is absent on POSIX
    msvcrt = None  # type: ignore
    import select

CFG_PATH = "capture_multi.yml"


def build_argparser() -> argparse.ArgumentParser:
    """Argument parser covering multi-shot and single-shot options."""
    p = capture_single_shot.build_argparser()
    p.set_defaults(config=CFG_PATH)
    p.add_argument("--captures", type=int)
    p.add_argument("--rest-ms", type=float, dest="rest_ms")
    p.add_argument(
        "--break-on-key",
        dest="break_on_key",
        action="store_true",
        help="Stop early if a key is pressed during the rest period",
    )
    return p


def _wait_with_break(rest_ms: float, allow_break: bool) -> bool:
    """Sleep for ``rest_ms`` milliseconds; return True if a key was pressed."""
    if not allow_break:
        time.sleep(rest_ms / 1000.0)
        return False

    print(
        f"Resting for {rest_ms} ms. Press any key to abort early...",
        flush=True,
    )
    end = time.time() + rest_ms / 1000.0
    while time.time() < end:
        if msvcrt:
            if msvcrt.kbhit():
                msvcrt.getch()
                return True
        else:
            dr, _, _ = select.select([sys.stdin], [], [], 0)
            if dr:
                sys.stdin.readline()
                return True
        time.sleep(0.05)
    return False

def main(cfg: dict) -> None:
    captures = int(cfg["captures"])
    rest_ms = float(cfg["rest_ms"])
    break_on_key = bool(cfg.get("break_on_key", False))
    for i in range(captures):
        capture_single_shot.main(cfg)
        if i < captures - 1:
            if _wait_with_break(rest_ms, break_on_key):
                print("Key pressed — stopping early.")
                break


if __name__ == "__main__":
    parser = build_argparser()
    args = parser.parse_args()
    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)
    cfg = capture_single_shot.apply_overrides(cfg, args)
    main(cfg)
