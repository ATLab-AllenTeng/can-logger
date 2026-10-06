"""Ctypes wrapper for a ControlCAN-compatible USB-CAN adapter.

The wrapper deliberately loads the vendor DLL only when a device is opened, so
imports and unit tests work on systems without Windows hardware drivers.
"""

import ctypes
import platform
from ctypes import POINTER, Structure, c_ubyte, c_uint
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from .models import CANFrame


class VCI_INIT_CONFIG(Structure):
  """Native VCI_INIT_CONFIG structure from the ControlCAN SDK."""

  _fields_ = [
    ("AccCode", c_uint),
    ("AccMask", c_uint),
    ("Reserved", c_uint),
    ("Filter", c_ubyte),
    ("Timing0", c_ubyte),
    ("Timing1", c_ubyte),
    ("Mode", c_ubyte),
  ]


class VCI_CAN_OBJ(Structure):
  """Native VCI_CAN_OBJ structure from the ControlCAN SDK."""

  _fields_ = [
    ("ID", c_uint),
    ("TimeStamp", c_uint),
    ("TimeFlag", c_ubyte),
    ("SendType", c_ubyte),
    ("RemoteFlag", c_ubyte),
    ("ExternFlag", c_ubyte),
    ("DataLen", c_ubyte),
    ("Data", c_ubyte * 8),
    ("Reserved", c_ubyte * 3),
  ]


class CANAdapterError(RuntimeError):
  """Raised when a ControlCAN operation cannot complete."""


class CANAdapter:
  """Open, configure, receive from, and close one ControlCAN device.

  A vendor DLL loader can be injected for tests. Production callers should use
  the default loader and place the matching 32-bit or 64-bit DLL in drivers/.
  """

  INVALID_RECEIVE_RESULT = 0xFFFFFFFF

  def __init__(
    self,
    dll_path="./drivers/ControlCAN.dll",
    dev_type=4,
    dev_index=0,
    receive_buffer_size=2000,
    dll_loader=None,
  ):
    if receive_buffer_size < 1:
      raise ValueError("receive_buffer_size must be positive")
    self.dll_path = Path(dll_path)
    self.dev_type = dev_type
    self.dev_index = dev_index
    self.receive_buffer_size = receive_buffer_size
    self._dll_loader = dll_loader
    self._dll = None
    self._is_open = False
    self._started_channels = set()
    self._receive_buffer = (VCI_CAN_OBJ * receive_buffer_size)()

  @property
  def is_open(self):
    return self._is_open

  def _load_dll(self):
    if self._dll is not None:
      return self._dll

    loader = self._dll_loader
    if loader is None:
      if platform.system() != "Windows":
        raise CANAdapterError("ControlCAN is supported only on Windows")
      if not self.dll_path.is_file():
        raise CANAdapterError(
          f"ControlCAN.dll was not found at: {self.dll_path.resolve()}"
        )
      loader = ctypes.WinDLL

    try:
      self._dll = loader(str(self.dll_path))
    except OSError as error:
      raise CANAdapterError(
        "Could not load ControlCAN.dll. Confirm that the DLL, its dependent "
        "files, and the Python interpreter use the same architecture."
      ) from error

    self._configure_signatures()
    return self._dll

  def _configure_signatures(self):
    """Configure signatures when the loader returns native ctypes functions."""
    signatures = {
      "VCI_OpenDevice": ([c_uint, c_uint, c_uint], c_uint),
      "VCI_CloseDevice": ([c_uint, c_uint], c_uint),
      "VCI_InitCAN": ([c_uint, c_uint, c_uint, POINTER(VCI_INIT_CONFIG)], c_uint),
      "VCI_StartCAN": ([c_uint, c_uint, c_uint], c_uint),
      "VCI_Receive": ([c_uint, c_uint, c_uint, POINTER(VCI_CAN_OBJ), c_uint, c_uint], c_uint),
    }
    for name, (argtypes, restype) in signatures.items():
      function = getattr(self._dll, name, None)
      if function is None:
        raise CANAdapterError(f"ControlCAN.dll does not export {name}")
      try:
        function.argtypes = argtypes
        function.restype = restype
      except AttributeError:
        # Lightweight fake DLL objects used in unit tests do not expose ctypes
        # metadata. They still receive the same positional arguments.
        pass

  def open_device(self):
    """Load the DLL and open the selected USB-CAN adapter."""
    if self._is_open:
      return
    dll = self._load_dll()
    result = dll.VCI_OpenDevice(self.dev_type, self.dev_index, 0)
    if int(result) != 1:
      raise CANAdapterError(
        "Could not open the USB-CAN device. Check USB connection, driver, "
        "device type, and device index."
      )
    self._is_open = True

  def init_can(self, can_index=0, timing0=0x00, timing1=0x1C, listen_only=True):
    """Initialize and start a CAN channel with the supplied timing registers."""
    if not self._is_open:
      raise CANAdapterError("Open the USB-CAN device before initializing CAN")
    if can_index not in (0, 1):
      raise ValueError("can_index must be 0 (CAN1) or 1 (CAN2)")
    if not 0 <= timing0 <= 0xFF or not 0 <= timing1 <= 0xFF:
      raise ValueError("CAN timing values must be unsigned bytes")

    config = VCI_INIT_CONFIG()
    config.AccCode = 0x00000000
    config.AccMask = 0xFFFFFFFF
    config.Reserved = 0
    config.Filter = 1
    config.Timing0 = timing0
    config.Timing1 = timing1
    config.Mode = 1 if listen_only else 0

    if self._dll.VCI_InitCAN(
      self.dev_type, self.dev_index, can_index, ctypes.byref(config)
    ) != 1:
      raise CANAdapterError(f"Could not initialize CAN channel {can_index + 1}")
    if self._dll.VCI_StartCAN(self.dev_type, self.dev_index, can_index) != 1:
      raise CANAdapterError(f"Could not start CAN channel {can_index + 1}")
    self._started_channels.add(can_index)

  def receive(self, can_index=0, wait_time=100):
    """Return all frames received during one ControlCAN receive call."""
    if can_index not in self._started_channels:
      raise CANAdapterError(f"CAN channel {can_index + 1} has not been started")
    if wait_time < 0:
      raise ValueError("wait_time must not be negative")

    count = int(
      self._dll.VCI_Receive(
        self.dev_type,
        self.dev_index,
        can_index,
        self._receive_buffer,
        self.receive_buffer_size,
        wait_time,
      )
    )
    if count == self.INVALID_RECEIVE_RESULT or count == -1:
      raise CANAdapterError("ControlCAN receive operation failed")
    if count < 0 or count > self.receive_buffer_size:
      raise CANAdapterError(f"ControlCAN returned invalid receive count: {count}")

    frames = []
    for index in range(count):
      native_frame = self._receive_buffer[index]
      data_length = int(native_frame.DataLen)
      if data_length > 8:
        raise CANAdapterError(f"ControlCAN returned invalid data length: {data_length}")
      payload = tuple(int(native_frame.Data[offset]) for offset in range(data_length))
      frames.append(
        CANFrame(
          can_id=int(native_frame.ID),
          is_extended=bool(native_frame.ExternFlag),
          is_remote=bool(native_frame.RemoteFlag),
          data_length=data_length,
          data=payload,
          received_at=datetime.now(),
          device_timestamp=int(native_frame.TimeStamp),
          has_device_timestamp=bool(native_frame.TimeFlag),
        )
      )
    return frames

  def close_device(self):
    """Close an opened device. This operation is safe to call repeatedly."""
    if not self._is_open:
      return
    try:
      result = self._dll.VCI_CloseDevice(self.dev_type, self.dev_index)
      if int(result) != 1:
        raise CANAdapterError("ControlCAN could not close the USB-CAN device")
    finally:
      self._is_open = False
      self._started_channels.clear()
