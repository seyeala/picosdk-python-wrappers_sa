from typing import List


class DaqOutputRunner:
    """In-memory collector for demonstration.

    The :py:meth:`write` method records values in :pyattr:`values` for later
    inspection by tests.
    """

    def __init__(self):
        self.values: List[float] = []

    def write(self, value: float) -> None:
        """Record *value* for later retrieval."""
        self.values.append(value)
