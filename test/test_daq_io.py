"""Demonstration of pairing input and output values.

This small example reads floating point values from ``pressures.csv`` using
:class:`daq_input_runner.DaqInputRunner` and writes them to
:class:`daq_output_runner.DaqOutputRunner`.  For each value a line is printed to
stdout linking the input and output values.

Run it directly::

    python test/test_daq_io.py

"""
from __future__ import annotations

import contextlib
import io
import unittest

from daq_input_runner import DaqInputRunner
from daq_output_runner import DaqOutputRunner


def run_demo(csv_path: str = "test/pressures.csv") -> None:
    """Run a short demonstration using the provided CSV file."""
    input_runner = DaqInputRunner(csv_path)
    output_runner = DaqOutputRunner()

    for value in input_runner.read():
        output_runner.write(value)
        print(f"Input {value} -> Output {value}")


class TestDaqIO(unittest.TestCase):
    def test_demo_prints_expected_pairs(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_demo("test/pressures.csv")
        self.assertEqual(
            buf.getvalue().strip().splitlines(),
            [
                "Input 1.0 -> Output 1.0",
                "Input 2.0 -> Output 2.0",
                "Input 3.0 -> Output 3.0",
            ],
        )


if __name__ == "__main__":
    run_demo()
