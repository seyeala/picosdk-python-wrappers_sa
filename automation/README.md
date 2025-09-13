# Automation scripts

Utility scripts for automating basic captures and checks with a PicoScope 5000A series oscilloscope.

## Contents

- `capture_single_shot.py` – captures a single-channel trace using settings from `capture_config_test.yml` and writes the result to CSV.
- `picoscope_self_test.py` – queries the connected unit and prints identity, capability and timing information for a quick hardware check.
- `capture_config_test.yml` – sample configuration used by `capture_single_shot.py`.

## Requirements

- Hardware: PicoScope 5000A series oscilloscope.
- Python packages: `picosdk` (drivers and this wrapper), `numpy`, and `PyYAML`.

## Example

Run a single-shot capture with the provided configuration and save samples to a CSV file:

```bash
cd automation
python capture_single_shot.py
```

`capture_single_shot.py` reads `capture_config_test.yml` by default. Edit the YAML file to change channel, trigger or output options.

To save output files with a timestamped name of the form
`M08-D24-H13-M05-S30-U.123.csv` (month-day-hour-minute-second-microseconds), set
`timestamp_filenames: true` in the configuration. When disabled, the
`csv_path` and `numpy_path` values are used directly.

