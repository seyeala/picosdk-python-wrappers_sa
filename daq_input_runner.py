import csv
from typing import Iterator


class DaqInputRunner:
    """Simple reader for demonstration purposes.

    It yields floating point values from the first column of a CSV file.
    Any header row or non-numeric values are ignored.
    """

    def __init__(self, csv_path: str):
        self.csv_path = csv_path

    def read(self) -> Iterator[float]:
        """Iterate through the values in *csv_path*.

        The CSV file is expected to contain a single column of numbers.  Lines
        that cannot be parsed are skipped.
        """
        with open(self.csv_path, newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if not row:
                    continue
                try:
                    yield float(row[0])
                except ValueError:
                    # Skip any header rows or malformed values.
                    continue
