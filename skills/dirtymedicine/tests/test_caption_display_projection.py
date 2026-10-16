"""Pronunciation collisions must preserve the original distinct display forms."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_semantic_captions import display_projection


class DisplayProjectionTests(unittest.TestCase):
    def test_same_spoken_phrase_can_have_distinct_original_forms(self):
        lesson = {"slides": [{"id": "01", "spoken_text": "enzyme, or enzyme.",
                   "display_segments": [{"spoken": "enzyme", "display": "enzyme"},
                                        {"spoken": ", or ", "display": ", or "},
                                        {"spoken": "enzyme", "display": "EZ"},
                                        {"spoken": ".", "display": "."}]}]}
        text, mapping, scenes = display_projection(lesson, {})
        self.assertEqual(text, "enzyme, or EZ.")
        self.assertEqual(scenes["01"], text)
        self.assertEqual(mapping[11:13], [(11, 17), (11, 17)])

    def test_legacy_aliases_still_preserve_scene_offsets(self):
        lesson = {"slides": [{"id": "01", "spoken_text": "A T P."},
                             {"id": "02", "spoken_text": "Next."}]}
        text, mapping, _ = display_projection(lesson, {"A T P": "ATP"})
        self.assertEqual(text, "ATP.Next.")
        self.assertEqual(mapping[4], (6, 7))

    def test_uncovered_speech_and_inserted_or_deleted_text_are_blocked(self):
        for segments in [[{"spoken": "one", "display": "one"}],
                         [{"spoken": "one two", "display": ""}],
                         [{"spoken": "", "display": "extra"},
                          {"spoken": "one two", "display": "one two"}]]:
            with self.subTest(segments=segments), self.assertRaises(ValueError):
                display_projection({"slides": [{"id": "01", "spoken_text": "one two",
                                                "display_segments": segments}]}, {})


if __name__ == "__main__":
    unittest.main()
