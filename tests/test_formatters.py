import csv
import io
import json

from venvdoctor.formatters import human_size, to_csv, to_json


def test_human_size_bytes():
    assert human_size(0) == "0.00 B"
    assert human_size(512) == "512.00 B"


def test_human_size_units_step_at_1024():
    assert human_size(1024) == "1.00 KB"
    assert human_size(1024 * 1024) == "1.00 MB"
    assert human_size(1024**3) == "1.00 GB"


def test_human_size_caps_at_petabytes():
    huge = 1024**6  # would be an EB, but PB is the largest unit supported
    assert human_size(huge).endswith("PB")


def test_to_json_round_trips_data():
    data = {"a": 1, "b": [1, 2, 3]}
    out = to_json(data)
    assert json.loads(out) == data


def test_to_csv_contains_header_and_rows():
    packages = [
        {"name": "numpy", "version": "1.26.0", "size_bytes": 1024},
        {"name": "pandas", "version": "2.2.1", "size_bytes": 3072},
    ]
    out = to_csv(packages, total_bytes=4096)
    rows = list(csv.reader(io.StringIO(out)))

    assert rows[0] == ["name", "version", "size_bytes", "size_human", "percentage"]
    # Sorted by size descending, so pandas (larger) comes first.
    assert rows[1][0] == "pandas"
    assert rows[1][4] == "75.00"
    assert rows[2][0] == "numpy"
    assert rows[2][4] == "25.00"


def test_to_csv_handles_zero_total_bytes():
    packages = [{"name": "empty", "version": "1.0", "size_bytes": 0}]
    out = to_csv(packages, total_bytes=0)
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[1][4] == "0.00"
