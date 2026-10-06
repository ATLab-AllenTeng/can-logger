"""Tests for frame validation and CSV formatting."""

import unittest
from datetime import datetime

from src.models import CANFrame


class CANFrameTests(unittest.TestCase):
  def test_standard_data_frame_formats_like_reference_spec(self):
    frame = CANFrame(
      can_id=0x123,
      is_extended=False,
      is_remote=False,
      data_length=3,
      data=(0x11, 0x22, 0xFF),
      received_at=datetime(2026, 10, 6, 8, 0, 1, 123456),
    )

    self.assertEqual(
      frame.csv_row,
      ["2026-10-06 08:00:01.123", "0x123", "STD", 3, "11 22 FF"],
    )

  def test_remote_frame_is_distinguished_without_payload(self):
    frame = CANFrame(
      can_id=0x18FEF100,
      is_extended=True,
      is_remote=True,
      data_length=0,
      data=(),
      received_at=datetime(2026, 10, 6, 8, 0, 1),
    )

    self.assertEqual(frame.csv_row[1:], ["0x18FEF100", "EXT_RTR", 0, ""])

  def test_rejects_invalid_standard_identifier(self):
    with self.assertRaises(ValueError):
      CANFrame(
        can_id=0x800,
        is_extended=False,
        is_remote=False,
        data_length=0,
        data=(),
        received_at=datetime.now(),
      )


if __name__ == "__main__":
  unittest.main()
