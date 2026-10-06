"""Threaded hourly CSV logging service for received CAN frames."""

import csv
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Protocol, TextIO

from .models import CANFrame


LOGGER = logging.getLogger(__name__)
CSV_HEADER = ["Timestamp", "CAN_ID", "Frame_Type", "Data_Length", "Data_Hex"]


class CANFrameSource(Protocol):
  """The minimum adapter interface needed by the logging service."""

  def receive(self, can_index=0, wait_time=100):
    """Return CANFrame objects received from the selected channel."""


class HourlyCANLogger:
  """Write CAN frames to UTF-8 CSV files and rotate them on the hour.

  The active hour file is opened when logging starts. While the service is
  running, an empty file is created at every hour boundary even if no messages
  arrive. Existing files for the same hour are safely appended without a
  duplicate CSV header.
  """

  def __init__(
    self,
    can_adapter: CANFrameSource,
    can_index=0,
    output_dir="./logs",
    receive_timeout_ms=100,
    idle_sleep_seconds=0.005,
    clock=None,
  ):
    if can_index not in (0, 1):
      raise ValueError("can_index must be 0 (CAN1) or 1 (CAN2)")
    if receive_timeout_ms < 0:
      raise ValueError("receive_timeout_ms must not be negative")
    if idle_sleep_seconds < 0:
      raise ValueError("idle_sleep_seconds must not be negative")

    self.adapter = can_adapter
    self.can_index = can_index
    self.output_dir = Path(output_dir)
    self.receive_timeout_ms = receive_timeout_ms
    self.idle_sleep_seconds = idle_sleep_seconds
    self._clock = clock or datetime.now
    self._stop_event = threading.Event()
    self._state_lock = threading.Lock()
    self._worker_thread = None
    self._worker_error = None
    self._current_hour = None
    self._current_file = None
    self._csv_writer = None

  @property
  def is_running(self):
    thread = self._worker_thread
    return bool(thread and thread.is_alive() and not self._stop_event.is_set())

  @property
  def worker_error(self):
    return self._worker_error

  def start_logging(self):
    """Create the active file and start the background receive loop."""
    with self._state_lock:
      if self._worker_thread is not None:
        raise RuntimeError("A logger instance cannot be started more than once")
      self.output_dir.mkdir(parents=True, exist_ok=True)
      self._get_file_handle()
      self._worker_thread = threading.Thread(
        target=self._log_loop,
        name=f"can-logger-channel-{self.can_index + 1}",
        daemon=False,
      )
      self._worker_thread.start()

  def _hour_key(self, moment):
    return moment.strftime("%Y%m%d_%H")

  def _file_path_for(self, moment):
    return self.output_dir / f"can_log_{moment.strftime('%Y%m%d_%H')}0000.csv"

  def _get_file_handle(self):
    """Return a writer for the current local hour, rotating if necessary."""
    now = self._clock()
    hour_key = self._hour_key(now)
    if self._csv_writer is not None and hour_key == self._current_hour:
      return self._csv_writer

    self._close_current_file()
    path = self._file_path_for(now)
    needs_header = not path.exists() or path.stat().st_size == 0
    self._current_file = path.open(
      "a",
      encoding="utf-8",
      newline="",
      buffering=1,
    )
    self._csv_writer = csv.writer(self._current_file)
    self._current_hour = hour_key
    if needs_header:
      self._csv_writer.writerow(CSV_HEADER)
    return self._csv_writer

  def _close_current_file(self):
    if self._current_file is not None:
      try:
        self._current_file.flush()
      finally:
        self._current_file.close()
    self._current_file = None
    self._csv_writer = None
    self._current_hour = None

  def _write_frame(self, frame: CANFrame):
    self._get_file_handle().writerow(frame.csv_row)

  def _log_loop(self):
    try:
      while not self._stop_event.is_set():
        # Calling this for idle cycles guarantees an empty file is still created
        # when the process crosses an hour boundary without traffic.
        self._get_file_handle()
        frames = self.adapter.receive(
          can_index=self.can_index,
          wait_time=self.receive_timeout_ms,
        )
        for frame in frames:
          self._write_frame(frame)
        if not frames and self.idle_sleep_seconds:
          self._stop_event.wait(self.idle_sleep_seconds)
    except Exception as error:
      self._worker_error = error
      LOGGER.exception("CAN logging worker stopped after an unrecoverable error")
      self._stop_event.set()

  def raise_if_failed(self):
    """Propagate a background receive error to the foreground caller."""
    if self._worker_error is not None:
      raise RuntimeError("CAN logging worker failed") from self._worker_error

  def stop_logging(self, join_timeout=None):
    """Stop receiving, flush the current file, and wait for the worker."""
    self._stop_event.set()
    thread = self._worker_thread
    if thread is not None and thread.is_alive():
      thread.join(join_timeout)
      if thread.is_alive():
        raise TimeoutError("CAN logging worker did not stop before the timeout")
    with self._state_lock:
      self._close_current_file()
