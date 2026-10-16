"""Reject expansion collisions before synthesis; preserve a genuinely spoken acronym."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_course_author_chain import alias_collisions


class AliasTests(unittest.TestCase):
    def test_full_name_or_alias_expanded_to_same_name_is_blocked(self):
        self.assertTrue(alias_collisions("The carbon process, or CP, starts here.",
                                         {"CP": "carbon process"}, "en-US"))

    def test_digits_and_spelled_digits_are_the_same_audible_name(self):
        self.assertTrue(alias_collisions("Process six, or P6, starts here.",
                                         {"P6": "Process-6"}, "en-US"))

    def test_actual_letter_pronunciation_is_allowed(self):
        self.assertEqual(alias_collisions("The carbon process, or CP, starts here.",
                                          {"CP": "C P"}, "en-US"), [])

    def test_ordinary_alias_use_and_different_or_option_are_allowed(self):
        self.assertEqual(alias_collisions("Choose the other process or CP. CP starts here.",
                                          {"CP": "carbon process"}, "en-US"), [])


if __name__ == "__main__":
    unittest.main()
