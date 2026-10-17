"""Prevent dev.cmd from silently opening an outdated or unrelated server."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


spec = spec_from_file_location("oss_start_dev", Path(__file__).parents[1] / "scripts/start_dev.py")
launcher = module_from_spec(spec)
spec.loader.exec_module(launcher)


class DevLauncherTests(unittest.TestCase):
    def test_current_server_is_reused_and_url_has_revision(self):
        running = {"revision": "current", "project_dir": str(launcher.PROJECT_DIR), "pid": 123}
        with patch.object(launcher, "application_revision", return_value="current"), \
             patch.object(launcher, "health", return_value=running), \
             patch.object(launcher.subprocess, "Popen") as start, \
             patch.object(launcher.webbrowser, "open") as browser:
            launcher.main()
        start.assert_not_called()
        browser.assert_called_once_with(launcher.URL + "/?v=current")

    def test_outdated_server_is_restarted_before_opening(self):
        stale = {"revision": "old", "project_dir": str(launcher.PROJECT_DIR), "pid": 123}
        current = {**stale, "revision": "current"}
        with patch.object(launcher, "application_revision", return_value="current"), \
             patch.object(launcher, "health", side_effect=[stale, current]), \
             patch.object(launcher, "port_in_use", return_value=False), \
             patch.object(launcher.os, "kill") as stop, \
             patch.object(launcher.subprocess, "Popen", return_value=Mock()) as start, \
             patch.object(launcher.webbrowser, "open") as browser:
            launcher.main()
        stop.assert_called_once_with(123, launcher.signal.SIGTERM)
        start.assert_called_once()
        browser.assert_called_once_with(launcher.URL + "/?v=current")

    def test_another_project_is_not_stopped(self):
        other = {"revision": "old", "project_dir": str(launcher.PROJECT_DIR.parent / "other"), "pid": 123}
        with patch.object(launcher, "health", return_value=other), \
             patch.object(launcher.os, "kill") as stop, \
             patch.object(launcher.webbrowser, "open") as browser:
            with self.assertRaisesRegex(RuntimeError, "another project"):
                launcher.main()
        stop.assert_not_called()
        browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
