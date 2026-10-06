"""Tests for ControlCAN ctypes wrapper behavior without physical hardware."""

import ctypes
import unittest

from src.can_adapter import CANAdapter, CANAdapterError, VCI_CAN_OBJ, VCI_INIT_CONFIG


class FakeDLL:
  def __init__(self):
    self.config = None
    self.closed = False
    self.receive_result = 1

  def VCI_OpenDevice(self, *_):
    return 1

  def VCI_CloseDevice(self, *_):
    self.closed = True
    return 1

  def VCI_InitCAN(self, _, __, ___, config_pointer):
    self.config = config_pointer._obj
    return 1

  def VCI_StartCAN(self, *_):
    return 1

  def VCI_Receive(self, _, __, ___, buffer, ____, _____):
    if self.receive_result == 1:
      buffer[0].ID = 0x18FEF100
      buffer[0].ExternFlag = 1
      buffer[0].RemoteFlag = 0
      buffer[0].DataLen = 2
      buffer[0].Data[0] = 0xAA
      buffer[0].Data[1] = 0x55
      buffer[0].TimeStamp = 42
      buffer[0].TimeFlag = 1
    return self.receive_result


class CANAdapterTests(unittest.TestCase):
  def setUp(self):
    self.dll = FakeDLL()
    self.adapter = CANAdapter(dll_loader=lambda _: self.dll)

  def tearDown(self):
    self.adapter.close_device()

  def test_native_structure_sizes_match_controlcan_layout(self):
    self.assertEqual(ctypes.sizeof(VCI_INIT_CONFIG), 16)
    self.assertEqual(ctypes.sizeof(VCI_CAN_OBJ), 24)

  def test_listen_only_configuration_and_receive_conversion(self):
    self.adapter.open_device()
    self.adapter.init_can(can_index=0, listen_only=True)
    frames = self.adapter.receive(can_index=0)

    self.assertEqual(self.dll.config.Mode, 1)
    self.assertEqual(len(frames), 1)
    self.assertEqual(frames[0].can_id, 0x18FEF100)
    self.assertEqual(frames[0].data, (0xAA, 0x55))
    self.assertTrue(frames[0].has_device_timestamp)

  def test_receive_error_is_not_silently_ignored(self):
    self.adapter.open_device()
    self.adapter.init_can(can_index=0)
    self.dll.receive_result = 0xFFFFFFFF

    with self.assertRaises(CANAdapterError):
      self.adapter.receive(can_index=0)


if __name__ == "__main__":
  unittest.main()
