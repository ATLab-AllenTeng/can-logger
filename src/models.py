"""Domain models and CSV formatting for CAN frames."""

from dataclasses import dataclass
from datetime import datetime
from typing import Tuple


@dataclass(frozen=True)
class CANFrame:
  """A frame received from a ControlCAN-compatible adapter."""

  can_id: int
  is_extended: bool
  is_remote: bool
  data_length: int
  data: Tuple[int, ...]
  received_at: datetime
  device_timestamp: int = 0
  has_device_timestamp: bool = False

  def __post_init__(self):
    if self.is_extended:
      maximum_id = 0x1FFFFFFF
    else:
      maximum_id = 0x7FF
    if not 0 <= self.can_id <= maximum_id:
      raise ValueError("CAN ID is outside the selected frame format")
    if not 0 <= self.data_length <= 8:
      raise ValueError("CAN data length must be between 0 and 8")
    if len(self.data) != self.data_length:
      raise ValueError("CAN data length does not match the payload")
    if any(not 0 <= byte <= 0xFF for byte in self.data):
      raise ValueError("CAN payload bytes must be unsigned octets")

  @property
  def frame_type(self):
    """Return CSV frame type while preserving remote-frame information."""
    base_type = "EXT" if self.is_extended else "STD"
    return f"{base_type}_RTR" if self.is_remote else base_type

  @property
  def formatted_id(self):
    """Format IDs according to the reference implementation in the spec."""
    width = 8 if self.is_extended else 3
    return f"0x{self.can_id:0{width}X}"

  @property
  def formatted_data(self):
    """Remote frames carry no CSV payload even when the controller buffer has data."""
    if self.is_remote:
      return ""
    return " ".join(f"{byte:02X}" for byte in self.data)

  @property
  def csv_row(self):
    timestamp = self.received_at.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return [timestamp, self.formatted_id, self.frame_type, self.data_length, self.formatted_data]
