import unittest
from unittest.mock import MagicMock, patch, call
import sys
import ctypes

# Mock ctypes.windll for non-Windows environments
if not hasattr(ctypes, 'windll'):
    ctypes.windll = MagicMock()
    ctypes.windll.user32 = MagicMock()
    ctypes.windll.user32.SendInput = MagicMock()

# Now we can import ReDSKYTunnel safely
import Resources.ReDSKYTunnel as rdt

class TestOrbiterInputBridge(unittest.TestCase):
    def setUp(self):
        self.bridge = rdt.OrbiterInputBridge()
        self.bridge.send_input = MagicMock()

    def test_transmit_keystroke_normal_down(self):
        self.bridge._transmit_keystroke(0x35, False, False)
        self.assertTrue(self.bridge.send_input.called)
        args, _ = self.bridge.send_input.call_args
        self.assertEqual(args[0], 1)
        # Checking size of struct
        self.assertTrue(args[2] > 0)

    def test_transmit_keystroke_extended_up(self):
        self.bridge._transmit_keystroke(0x1C, True, True)
        self.assertTrue(self.bridge.send_input.called)

    def test_process_network_event_invalid_msg(self):
        self.bridge.process_network_event("INVALIDMSG")
        self.assertFalse(self.bridge.send_input.called)

    def test_process_network_event_unknown_key(self):
        self.bridge.process_network_event("UNKNOWN_D")
        self.assertFalse(self.bridge.send_input.called)

    @patch('time.sleep')
    def test_process_network_event_key_down(self, mock_sleep):
        # Key down (first key pressed) should send LSHIFT down then KEY down
        self.bridge._transmit_keystroke = MagicMock()
        self.bridge.process_network_event("VERB_D")

        self.assertEqual(len(self.bridge.active_keys), 1)
        self.assertIn("VERB", self.bridge.active_keys)

        expected_calls = [
            call(rdt.DIK_LSHIFT, False, False),
            call(0x35, True, False)
        ]
        self.bridge._transmit_keystroke.assert_has_calls(expected_calls)
        mock_sleep.assert_called_once_with(0.05)

    @patch('time.sleep')
    def test_process_network_event_multiple_key_down(self, mock_sleep):
        # Second key down should not send LSHIFT again
        self.bridge.active_keys.add("NOUN")
        self.bridge._transmit_keystroke = MagicMock()

        self.bridge.process_network_event("VERB_D")

        self.assertEqual(len(self.bridge.active_keys), 2)
        expected_calls = [
            call(0x35, True, False)
        ]
        self.bridge._transmit_keystroke.assert_has_calls(expected_calls)
        mock_sleep.assert_not_called()

    @patch('time.sleep')
    def test_process_network_event_key_up(self, mock_sleep):
        self.bridge.active_keys.add("VERB")
        self.bridge._transmit_keystroke = MagicMock()

        # Last key released should send KEY up then LSHIFT up
        self.bridge.process_network_event("VERB_U")

        self.assertEqual(len(self.bridge.active_keys), 0)
        expected_calls = [
            call(0x35, True, True),
            call(rdt.DIK_LSHIFT, False, True)
        ]
        self.bridge._transmit_keystroke.assert_has_calls(expected_calls)
        mock_sleep.assert_called_once_with(0.05)

    @patch('time.sleep')
    def test_process_network_event_multiple_key_up(self, mock_sleep):
        self.bridge.active_keys.add("VERB")
        self.bridge.active_keys.add("NOUN")
        self.bridge._transmit_keystroke = MagicMock()

        # Not the last key released, should not send LSHIFT up
        self.bridge.process_network_event("VERB_U")

        self.assertEqual(len(self.bridge.active_keys), 1)
        expected_calls = [
            call(0x35, True, True)
        ]
        self.bridge._transmit_keystroke.assert_has_calls(expected_calls)
        mock_sleep.assert_not_called()

class TestOrbiterWatchdog(unittest.TestCase):
    @patch('time.sleep')
    @patch('os._exit')
    @patch('subprocess.check_output')
    def test_watchdog_starts_and_stops(self, mock_check_output, mock_exit, mock_sleep):
        # The loop runs indefinitely, so we must exit out using an exception
        # on the third iteration
        mock_sleep.side_effect = [None, Exception("Stop Loop")]
        mock_check_output.side_effect = [
            b"orbiter.exe is running", # Iteration 1: is_running becomes True
            b"something else"          # Iteration 2: is_running becomes False, exit triggered, stop loop!
        ]

        try:
            rdt.orbiter_watchdog()
        except Exception as e:
            self.assertEqual(str(e), "Stop Loop")

        mock_exit.assert_called_once_with(0)

    @patch('time.sleep', side_effect=Exception("Stop Loop"))
    @patch('os._exit')
    @patch('subprocess.check_output')
    def test_watchdog_exception_handling(self, mock_check_output, mock_exit, mock_sleep):
        # Simulate exception in check_output
        mock_check_output.side_effect = Exception("Subprocess error")

        try:
            rdt.orbiter_watchdog()
        except Exception as e:
            self.assertEqual(str(e), "Stop Loop")

        # Since it wasn't running before, it shouldn't exit
        mock_exit.assert_not_called()

if __name__ == '__main__':
    unittest.main()
