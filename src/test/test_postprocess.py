"""Discovery, origin and reload of postprocessor modules.

The menu can only rule site-local modules apart from the ones that ship with
the software if the loader records where each came from, and refresh can only
be safe if reloading keeps the containers every other holder is pointing at.
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils import postprocess
from utils.postprocess import BUILTIN, CUSTOM, get_postprocessors, reload_postprocessors


class TestPostprocessorDiscovery(unittest.TestCase):
    def test_the_built_in_modules_are_tagged_as_built_in(self):
        builtin = get_postprocessors(BUILTIN)
        self.assertIn("excel_export", builtin)
        for module_name in builtin:
            self.assertEqual(postprocess.postprocessor_origins[module_name], BUILTIN)

    def test_every_module_is_one_origin_or_the_other(self):
        self.assertEqual(
            set(get_postprocessors()),
            set(get_postprocessors(BUILTIN)) | set(get_postprocessors(CUSTOM)),
        )

    def test_a_user_module_shadowing_a_built_in_name_is_recorded_as_custom(self):
        """It is site-local code now, whatever the name it took over."""
        with patch("utils.postprocess.load_modules_from_folder") as loader, \
             patch("os.path.exists", return_value=True):
            loader.side_effect = [
                {"excel_export": SimpleNamespace(), "json_export": SimpleNamespace()},
                {"excel_export": SimpleNamespace()},
            ]
            reload_postprocessors()

        self.assertEqual(postprocess.postprocessor_origins["excel_export"], CUSTOM)
        self.assertEqual(postprocess.postprocessor_origins["json_export"], BUILTIN)

        reload_postprocessors()  # back to what is actually on disk

    def test_reload_keeps_the_containers_other_holders_point_at(self):
        modules = get_postprocessors()
        origins = postprocess.postprocessor_origins

        reload_postprocessors()

        self.assertIs(get_postprocessors(), modules)
        self.assertIs(postprocess.postprocessor_origins, origins)
        self.assertIn("excel_export", modules)


if __name__ == "__main__":
    unittest.main()
