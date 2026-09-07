import json
import unittest

from mywhoosh_virtual_shifting import gear_message
from mywhoosh_link_emulator import handle_message
from cycplus_bc2_openbikecontrol import button_states, notify_handler
from openbikecontrol_virtual_device import SHIFT_DOWN, SHIFT_UP
from mywhoosh_openbikecontrol_emulator import decode_button_state


class GearMessageTests(unittest.TestCase):
    def test_up_message_matches_mywhoosh_link_protocol(self):
        self.assertEqual(
            json.loads(gear_message(1)),
            {
                "MessageType": "Controls",
                "InGameControls": {"GearShifting": "1"},
            },
        )

    def test_down_message_matches_mywhoosh_link_protocol(self):
        self.assertEqual(
            json.loads(gear_message(-1)),
            {
                "MessageType": "Controls",
                "InGameControls": {"GearShifting": "-1"},
            },
        )

    def test_invalid_direction_is_rejected(self):
        with self.assertRaises(ValueError):
            gear_message(0)


class EmulatorMessageTests(unittest.TestCase):
    def test_emulator_decodes_gear_message(self):
        message = handle_message(gear_message(-1).rstrip(b"\n"))
        self.assertEqual(message["InGameControls"]["GearShifting"], "-1")

    def test_emulator_rejects_unknown_control(self):
        with self.assertRaises(ValueError):
            handle_message(b'{"MessageType":"Controls","InGameControls":{"Steering":"1"}}')


class OpenBikeControlMessageTests(unittest.TestCase):
    def test_bc2_uart_button_fields(self):
        self.assertEqual(button_states(bytes.fromhex("fe ef ff ee 02 06 01 03 00"), 1, 1), (True, False))
        self.assertEqual(button_states(bytes.fromhex("fe ef ff ee 02 06 03 01 00"), 1, 1), (False, True))
        self.assertEqual(button_states(bytes.fromhex("fe ef ff ee 02 06 03 03 00"), 1, 1), (False, False))

    def test_bc2_short_press_sends_press_before_release(self):
        class Device:
            def __init__(self):
                self.states = []

            def send_button(self, button_id, state):
                self.states.append((button_id, state))
                return True

        device = Device()
        previous = [(False, False)]
        handle = notify_handler(device, 1, 1, previous)

        handle("bc2", bytearray.fromhex("fe ef ff ee 02 06 01 03 00"))
        handle("bc2", bytearray.fromhex("fe ef ff ee 02 06 03 03 00"))

        self.assertEqual(device.states, [(1, 1), (1, 0)])

    def test_bc2_repeated_reports_do_not_break_long_press(self):
        class Device:
            def __init__(self):
                self.states = []

            def send_button(self, button_id, state):
                self.states.append((button_id, state))
                return True

        device = Device()
        previous = [(False, False)]
        handle = notify_handler(device, 1, 1, previous)

        press = bytearray.fromhex("fe ef ff ee 02 06 01 03 00")
        handle("bc2", press)
        handle("bc2", press)

        self.assertEqual(device.states, [(1, 1)])

    def test_shift_messages_use_official_binary_format(self):
        self.assertEqual(SHIFT_UP, bytes((0x01, 0x01, 0x01)))
        self.assertEqual(SHIFT_DOWN, bytes((0x01, 0x02, 0x01)))

    def test_mywhoosh_emulator_decodes_shift_frames(self):
        self.assertEqual(decode_button_state(SHIFT_UP), [(0x01, 0x01)])
        self.assertEqual(decode_button_state(SHIFT_DOWN), [(0x02, 0x01)])


if __name__ == "__main__":
    unittest.main()
