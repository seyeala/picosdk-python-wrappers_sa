# -*- coding: utf-8 -*-
# capture_multi_shot.py — run repeated captures using capture_single_shot

import time
import yaml
import capture_single_shot

CFG_PATH = "capture_multi.yml"

def main(cfg: dict) -> None:
    captures = int(cfg["captures"])
    rest_ms = float(cfg["rest_ms"])
    for i in range(captures):
        capture_single_shot.main(cfg)
        if i < captures - 1:
            time.sleep(rest_ms / 1000.0)


if __name__ == "__main__":
    with open(CFG_PATH, "r") as f:
        cfg = yaml.safe_load(f)
    main(cfg)
