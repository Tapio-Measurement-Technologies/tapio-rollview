import sys
import unittest
from unittest.mock import MagicMock, patch, call

os_environ_patch = patch.dict("os.environ", {"QT_QPA_PLATFORM": "offscreen"})
os_environ_patch.start()


class TestMainSettingsFileFlag(unittest.TestCase):
    def _run_main(self, argv, mock_window=None, mock_app=None):
        if mock_window is None:
            mock_window = MagicMock()
        if mock_app is None:
            mock_app = MagicMock()
            mock_app.exec.return_value = 0

        # QApplication, MainWindow, QIcon are imported locally inside main(),
        # so patch them at their source modules.
        with patch.object(sys, "argv", ["main.py"] + argv), \
             patch("PySide6.QtWidgets.QApplication", return_value=mock_app), \
             patch("gui.main_window.MainWindow", return_value=mock_window), \
             patch("PySide6.QtGui.QIcon"):
            import main
            main.main()

        return mock_window, mock_app

    def test_settings_file_flag_calls_load_with_path(self):
        mock_window, _ = self._run_main(["--settings-file", "/tmp/custom.json"])
        mock_window.load_settings_file_from_path.assert_called_once_with("/tmp/custom.json")

    def test_no_settings_file_flag_does_not_call_load(self):
        mock_window, _ = self._run_main([])
        mock_window.load_settings_file_from_path.assert_not_called()

    def test_settings_file_flag_calls_show_before_load(self):
        call_order = []
        mock_window = MagicMock()
        mock_window.show.side_effect = lambda: call_order.append("show")
        mock_window.load_settings_file_from_path.side_effect = lambda p: call_order.append("load")
        mock_app = MagicMock()
        mock_app.exec.return_value = 0

        self._run_main(["--settings-file", "/tmp/x.json"], mock_window=mock_window, mock_app=mock_app)

        self.assertEqual(call_order, ["show", "load"])

    def test_unknown_qt_args_are_ignored(self):
        mock_window, _ = self._run_main(["-platform", "offscreen", "--settings-file", "/tmp/a.json"])
        mock_window.load_settings_file_from_path.assert_called_once_with("/tmp/a.json")


class TestSettingsSysArgvGuard(unittest.TestCase):
    """Tests that named flags in sys.argv don't trigger local_settings loading."""

    def _load_settings_module(self, argv):
        """Re-execute the settings.py argv-check block with a given argv."""
        import importlib
        import settings as s

        called_with = {}

        def fake_load(path):
            called_with["path"] = path
            return {}

        with patch.object(sys, "argv", argv), \
             patch.object(s, "load_local_settings", side_effect=fake_load):
            # Re-run only the argv-check block
            if len(argv) > 1 and not argv[1].startswith("-"):
                import os
                supplied = argv[1]
                if os.path.exists(supplied):
                    fake_load(supplied)

        return called_with

    def test_named_flag_does_not_trigger_local_settings_load(self):
        result = self._load_settings_module(["main.py", "--settings-file", "/tmp/x.json"])
        self.assertEqual(result, {})

    def test_positional_nonexistent_path_does_not_trigger_load(self):
        result = self._load_settings_module(["main.py", "/nonexistent/path.py"])
        self.assertEqual(result, {})

    def test_positional_existing_path_triggers_load(self):
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            tmp_path = f.name
        try:
            result = self._load_settings_module(["main.py", tmp_path])
            self.assertEqual(result.get("path"), tmp_path)
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
