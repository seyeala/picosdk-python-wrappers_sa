# -*- coding: utf-8 -*-
# capture_multi_shot.py — run repeated captures using capture_single_shot
# Reads settings from YAML and allows command-line overrides

import argparse
import time
import yaml

import capture_single_shot

CFG_PATH = "capture_multi.yml"


def build_argparser() -> argparse.ArgumentParser:
    """Argument parser covering multi-shot and single-shot options."""
    p = capture_single_shot.build_argparser()
    p.set_defaults(config=CFG_PATH)
    p.add_argument("--captures", type=int)
    p.add_argument("--rest-ms", type=float, dest="rest_ms")
    return p

def main(cfg: dict) -> None:
    captures = int(cfg["captures"])
    rest_ms = float(cfg["rest_ms"])
    for i in range(captures):
        capture_single_shot.main(cfg)
        if i < captures - 1:
            time.sleep(rest_ms / 1000.0)


if __name__ == "__main__":
    parser = build_argparser()
    args = parser.parse_args()
    with open(args.config, "r") as f:
        cfg = yaml.safe_load(f)
    cfg = capture_single_shot.apply_overrides(cfg, args)
    main(cfg)
