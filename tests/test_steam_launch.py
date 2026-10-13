import unittest
from steam_launch import configure

class SteamLaunchTests(unittest.TestCase):
    def test_changes_only_runtime_settings_and_keeps_fullscreen_and_autoexec(self):
        data=b'[sdl]\r\nfullscreen=true\r\noutput=ddraw\r\n[dosbox]\r\nmemsize=63\r\n[cpu]\r\ncore=auto\r\ncycles=auto\r\n[autoexec]\r\nmount C: ..\r\nspire.bat\r\n'
        expected=data.replace(b'core=auto',b'core=dynamic').replace(b'cycles=auto',b'cycles=max')
        self.assertEqual(configure(data),expected)
        self.assertEqual(configure(expected),expected)
    def test_incomplete_configuration_is_rejected(self):
        with self.assertRaises(ValueError):configure(b'[cpu]\ncore=auto\ncycles=auto\n')
    def test_duplicate_configuration_is_rejected(self):
        with self.assertRaises(ValueError):configure(b'[sdl]\noutput=ddraw\noutput=surface\n')

if __name__=='__main__':unittest.main()
