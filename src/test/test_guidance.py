"""The shared guidance composer.

The rules worth pinning down are the ones a caller can break without noticing:
a line with nothing to say has to come out empty rather than as a stray
separator, and a composite has to carry its line on every part of itself,
because Qt asks no parent for a status tip.
"""

import unittest

from theme.guidance import SEPARATOR, compose, set_guidance, set_guidance_everywhere

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from test.qtcleanup import destroy


class TestComposeGuidance(unittest.TestCase):

    def test_the_three_parts_come_out_in_one_order(self):
        text = compose("Mean", "Alert limits: 1.0, 5.0", "Click to edit")
        self.assertLess(text.index("Mean"), text.index("Alert limits"))
        self.assertLess(text.index("Alert limits"), text.index("Click to edit"))

    def test_it_is_one_line(self):
        # The row it lands in is one line high; a newline would be shown as a
        # box or swallowed, neither of which is a message.
        text = compose("Open folder", ["Somewhere", "C:/rolls"], "Click to open")
        self.assertNotIn("\n", text)
        self.assertEqual(text.count(SEPARATOR), 3)

    def test_empty_detail_lines_are_dropped(self):
        # A path that has not been chosen yet is "", and a dangling separator
        # in the row reads as a rendering fault.
        self.assertEqual(compose("Open folder", ["", None]), "Open folder")

    def test_nothing_to_say_is_no_guidance_at_all(self):
        # "" is what Qt reads as "no status tip", so a control whose detail has
        # gone away stops claiming the row.
        self.assertEqual(compose(), "")
        self.assertEqual(compose(None, [], None), "")

    def test_the_text_is_left_alone(self):
        # Plain text in a plain label: no markup to escape, and none added.
        text = compose("R&D <roll>", "a > b")
        self.assertIn("R&D <roll>", text)
        self.assertIn("a > b", text)


class TestSetGuidance(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_it_puts_the_composed_line_on_the_widget(self):
        label = QLabel()
        try:
            returned = set_guidance(label, "Mean", "Alert limits", "Click to edit")
            self.assertEqual(label.statusTip(), returned)
            self.assertIn("Mean", label.statusTip())
            # Guidance, not a popup.
            self.assertEqual(label.toolTip(), "")
        finally:
            destroy(label)

    def test_a_composite_carries_the_line_on_every_part(self):
        # Qt emits the status tip of the widget the pointer entered and does
        # not look up the parent chain, so a tile covered by its own labels
        # would otherwise go quiet exactly where the pointer lands.
        holder = QWidget()
        try:
            layout = QVBoxLayout(holder)
            children = [QLabel("one"), QLabel("two")]
            for child in children:
                layout.addWidget(child)

            text = set_guidance_everywhere(holder, "Mean", "2.4 g", "Click to edit")

            self.assertEqual(holder.statusTip(), text)
            for child in children:
                self.assertEqual(child.statusTip(), text)
        finally:
            destroy(holder)


if __name__ == "__main__":
    unittest.main()
