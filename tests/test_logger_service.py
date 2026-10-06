"""Tests for hourly CSV rotation without CAN hardware."""

import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from src.logger_service import CSV_HEADER, HourlyCANLogger
from src.models import CANFrame


class IdleAdapter:
  def receive(self, can_index=0, wait_time=100):
    return []


class HourlyLoggerTests(unittest.TestCase):
  def test_rotation_creates_hourly_files_and_writes_header_once(self):
    moments = [
      datetime(2026, 10, 6, 8, 59, 59),
      datetime(2026, 10, 6, 9, 0, 0),
    ]
    index = [0]

    def clock():
      return moments[index[0]]

    frame = CANFrame(
      can_id=0x123,
      is_extended=False,
      is_remote=False,
      data_length=2,
      data=(0x11, 0x22),
      received_at=datetime(2026, 10, 6, 8, 59, 59, 1),
    )

    with tempfile.TemporaryDirectory() as directory:
      service = HourlyCANLogger(IdleAdapter(), output_dir=directory, clock=clock)
      service.output_dir.mkdir(parents=True, exist_ok=True)
      service._get_file_handle()
      service._write_frame(frame)
      index[0] = 1
      service._get_file_handle()
      service.stop_logging()

      first_path = Path(directory) / "can_log_20261006_080000.csv"
      second_path = Path(directory) / "can_log_20261006_090000.csv"
      with first_path.open(newline="", encoding="utf-8") as file_handle:
        first_rows = list(csv.reader(file_handle))
      with second_path.open(newline="", encoding="utf-8") as file_handle:
        second_rows = list(csv.reader(file_handle))

    self.assertEqual(first_rows[0], CSV_HEADER)
    self.assertEqual(first_rows[1][1:], ["0x123", "STD", "2", "11 22"])
    self.assertEqual(second_rows, [CSV_HEADER])

  def test_start_creates_current_hour_file_without_traffic(self):
    with tempfile.TemporaryDirectory() as directory:
      service = HourlyCANLogger(IdleAdapter(), output_dir=directory)
      service.start_logging()
      service.stop_logging()

      created = list(Path(directory).glob("can_log_*.csv"))
      self.assertEqual(len(created), 1)


if __name__ == "__main__":
  unittest.main()
