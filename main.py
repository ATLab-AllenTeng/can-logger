"""Command-line entry point for the USB-CAN hourly logger."""

import argparse
import logging
import sys
import time
from pathlib import Path

from src.can_adapter import CANAdapter, CANAdapterError
from src.logger_service import HourlyCANLogger


PROJECT_ROOT = Path(__file__).resolve().parent
BITRATE_TIMINGS = {
  "1000k": (0x00, 0x14),
  "500k": (0x00, 0x1C),
  "250k": (0x01, 0x1C),
  "125k": (0x03, 0x1C),
  "100k": (0x04, 0x1C),
  "50k": (0x09, 0x1C),
}
BITRATE_ALIASES = {
  "1m": "1000k",
  "1000000": "1000k",
  "500000": "500k",
  "250000": "250k",
  "125000": "125k",
  "100000": "100k",
  "50000": "50k",
}


def parse_byte(value):
  try:
    parsed = int(value, 0)
  except ValueError as error:
    raise argparse.ArgumentTypeError("must be an integer such as 0x1C") from error
  if not 0 <= parsed <= 0xFF:
    raise argparse.ArgumentTypeError("must be in the range 0x00 through 0xFF")
  return parsed


def parse_bitrate(value):
  normalized = value.lower().replace("bps", "").replace(" ", "")
  normalized = BITRATE_ALIASES.get(normalized, normalized)
  if normalized not in BITRATE_TIMINGS:
    choices = ", ".join(BITRATE_TIMINGS)
    raise argparse.ArgumentTypeError(f"unsupported bitrate. Choose one of: {choices}")
  return normalized


def build_parser():
  parser = argparse.ArgumentParser(
    description="Log CAN1 or CAN2 traffic to UTF-8 CSV files, rotated hourly."
  )
  parser.add_argument(
    "--dll",
    type=Path,
    default=PROJECT_ROOT / "drivers" / "ControlCAN.dll",
    help="Path to the vendor-provided ControlCAN.dll",
  )
  parser.add_argument("--channel", type=int, choices=(0, 1), default=0)
  parser.add_argument("--device-type", type=int, default=4)
  parser.add_argument("--device-index", type=int, default=0)
  parser.add_argument("--bitrate", type=parse_bitrate, default="500k")
  parser.add_argument(
    "--timing0",
    type=parse_byte,
    help="Override Timing0 from the vendor SDK table",
  )
  parser.add_argument(
    "--timing1",
    type=parse_byte,
    help="Override Timing1 from the vendor SDK table",
  )
  parser.add_argument(
    "--normal-mode",
    action="store_true",
    help="Use normal mode instead of passive listen-only mode. Normal mode can ACK frames.",
  )
  parser.add_argument(
    "--output-dir",
    type=Path,
    default=PROJECT_ROOT / "logs",
  )
  parser.add_argument("--buffer-size", type=int, default=2000)
  parser.add_argument("--receive-timeout-ms", type=int, default=100)
  parser.add_argument("--verbose", action="store_true")
  return parser


def main(argv=None):
  args = build_parser().parse_args(argv)
  logging.basicConfig(
    level=logging.DEBUG if args.verbose else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  logger = None
  adapter = None
  exit_code = 0
  timing0, timing1 = BITRATE_TIMINGS[args.bitrate]
  if args.timing0 is not None:
    timing0 = args.timing0
  if args.timing1 is not None:
    timing1 = args.timing1

  try:
    adapter = CANAdapter(
      dll_path=args.dll,
      dev_type=args.device_type,
      dev_index=args.device_index,
      receive_buffer_size=args.buffer_size,
    )
    adapter.open_device()
    adapter.init_can(
      can_index=args.channel,
      timing0=timing0,
      timing1=timing1,
      listen_only=not args.normal_mode,
    )

    logger = HourlyCANLogger(
      can_adapter=adapter,
      can_index=args.channel,
      output_dir=args.output_dir,
      receive_timeout_ms=args.receive_timeout_ms,
    )
    logger.start_logging()
    mode = "normal" if args.normal_mode else "listen-only"
    print(
      f"CAN{args.channel + 1} logger started at {args.bitrate} "
      f"in {mode} mode. Press Ctrl+C to stop."
    )

    while True:
      time.sleep(0.5)
      logger.raise_if_failed()
  except KeyboardInterrupt:
    print("Stopping CAN logger safely...")
  except (CANAdapterError, OSError, RuntimeError, ValueError) as error:
    logging.getLogger(__name__).error("CAN logger failed: %s", error)
    exit_code = 1
  finally:
    if logger is not None:
      try:
        logger.stop_logging()
      except (OSError, RuntimeError, TimeoutError) as error:
        logging.getLogger(__name__).error("Could not close the log file cleanly: %s", error)
        exit_code = 1
    if adapter is not None:
      try:
        adapter.close_device()
      except CANAdapterError as error:
        logging.getLogger(__name__).error("Could not close the CAN device cleanly: %s", error)
        exit_code = 1

  return exit_code


if __name__ == "__main__":
  sys.exit(main())
