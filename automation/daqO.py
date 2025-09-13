import argparse
import asyncio
import random
import re
from typing import Dict, Iterable

import yaml

CFG_PATH = "daqO.yml"


def parse_time(value) -> float:
    """Parse time values such as '1s' or '500ms' into seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s)", str(value).strip())
    if not m:
        raise ValueError(f"Invalid time format: {value}")
    mag, unit = m.groups()
    mag = float(mag)
    return mag / 1000.0 if unit == "ms" else mag


async def publish_ao(payload: Dict[int, float]):
    """Publish analog output values.

    Placeholder implementation; in real deployments this should interface
    with the hardware or external system responsible for generating the
    analogue outputs."""
    # This function intentionally left as a stub. It may be replaced by
    # an actual implementation by users of the library.
    pass


async def run(cfg: dict) -> None:
    device = cfg["device"]
    channels: Iterable[int] = cfg["channels"]
    interval = parse_time(cfg["interval"])
    low = float(cfg["low"])
    high = float(cfg["high"])
    rng = random.Random(cfg.get("seed"))

    try:
        while True:
            payload = {ch: rng.uniform(low, high) for ch in channels}
            await publish_ao(payload)
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        payload = {ch: 0.0 for ch in channels}
        await publish_ao(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple analog output generator")
    parser.add_argument("-c", "--config", default=CFG_PATH, help="Path to YAML configuration file")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    asyncio.run(run(cfg))
