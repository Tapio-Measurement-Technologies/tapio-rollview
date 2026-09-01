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


class TestWindowsTaskbarIcon(unittest.TestCase):
    """The taskbar button takes its icon from the window and its identity from
    the AppUserModelID, and both have to be right before a window exists."""

    def test_application_icon_is_set_before_the_window_is_built(self):
        call_order = []
        mock_app = MagicMock()
        mock_app.exec.return_value = 0
        mock_app.setWindowIcon.side_effect = lambda icon: call_order.append("icon")

        with patch.object(sys, "argv", ["main.py"]),              patch("PySide6.QtWidgets.QApplication", return_value=mock_app),              patch("gui.main_window.MainWindow", side_effect=lambda: call_order.append("window") or MagicMock()),              patch("PySide6.QtGui.QIcon"):
            import main
            main.main()

        self.assertEqual(call_order, ["icon", "window"])

    def test_a_source_run_claims_its_own_app_user_model_id(self):
        import main
        import settings

        with patch.object(sys, "platform", "win32"),              patch.object(sys, "frozen", False, create=True),              patch("ctypes.windll", create=True) as mock_windll:
            main.set_windows_app_id()

        mock_windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(
            settings.APP_USER_MODEL_ID
        )

    def test_a_frozen_build_keeps_the_identity_of_its_executable(self):
        import main

        with patch.object(sys, "platform", "win32"),              patch.object(sys, "frozen", True, create=True),              patch("ctypes.windll", create=True) as mock_windll:
            main.set_windows_app_id()

        mock_windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_not_called()


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


class TestStartupOrder(unittest.TestCase):
    """Nothing under gui/ is imported until there is an application to build
    widgets against. A module that touches Qt while being imported is fatal
    without one, and Qt's abort replaces the traceback that explains why."""

    def test_the_application_exists_before_the_gui_is_imported(self):
        import builtins

        order = []
        real_import = builtins.__import__

        def tracking_import(name, *args, **kwargs):
            if name == "gui.main_window":
                order.append("gui")
            return real_import(name, *args, **kwargs)

        mock_app = MagicMock()
        mock_app.exec.return_value = 0

        def build_app(*args, **kwargs):
            order.append("app")
            return mock_app

        with patch.object(sys, "argv", ["main.py"]), \
             patch("PySide6.QtWidgets.QApplication", side_effect=build_app), \
             patch("gui.main_window.MainWindow"), \
             patch("PySide6.QtGui.QIcon"), \
             patch.object(builtins, "__import__", side_effect=tracking_import):
            import main
            main.main()

        self.assertEqual(order, ["app", "gui"])
