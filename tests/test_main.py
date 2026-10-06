"""Tests for safe command-line option parsing."""

import unittest

from main import BITRATE_TIMINGS, build_parser, parse_bitrate, parse_byte


class MainArgumentTests(unittest.TestCase):
  def test_bitrate_aliases_resolve_to_documented_presets(self):
    self.assertEqual(parse_bitrate("500000"), "500k")
    self.assertEqual(parse_bitrate("1M"), "1000k")
    self.assertEqual(BITRATE_TIMINGS[parse_bitrate("250k")], (0x01, 0x1C))

  def test_timing_override_accepts_hexadecimal_byte(self):
    self.assertEqual(parse_byte("0x1C"), 0x1C)

  def test_default_configuration_is_passive_can1_500k(self):
    args = build_parser().parse_args([])
    self.assertEqual(args.channel, 0)
    self.assertEqual(args.bitrate, "500k")
    self.assertFalse(args.normal_mode)


if __name__ == "__main__":
  unittest.main()
