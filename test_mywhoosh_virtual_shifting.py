import json
import unittest

from mywhoosh_virtual_shifting import gear_message
from mywhoosh_link_emulator import handle_message
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
    def test_shift_messages_use_official_binary_format(self):
        self.assertEqual(SHIFT_UP, bytes((0x01, 0x01, 0x01)))
        self.assertEqual(SHIFT_DOWN, bytes((0x01, 0x02, 0x01)))

    def test_mywhoosh_emulator_decodes_shift_frames(self):
        self.assertEqual(decode_button_state(SHIFT_UP), [(0x01, 0x01)])
        self.assertEqual(decode_button_state(SHIFT_DOWN), [(0x02, 0x01)])


if __name__ == "__main__":
    unittest.main()
