"""Separate adapter provenance metadata from actually selected model weights."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_voice_recipe import audit


class VoiceRecipeTests(unittest.TestCase):
    def run_case(self, loaded, actual, enabled=None):
        adapter = {"sha256": "adapter provenance"}
        if enabled is not None:
            adapter["enabled"] = enabled
        profile = {
            "adapter_loaded": loaded,
            "adapter": adapter,
            "generation": {"max_new_tokens": 18500},
            "model": {"revision": "m"},
            "codec": {"revision": "c"},
            "reference_sha256": "r",
        }
        receipt = {
            "adapter_loaded": actual,
            "adapter_sha256": "adapter provenance" if actual else None,
            "settings": {"max_new_tokens": 18500},
            "model_revision": "m",
            "codec_revision": "c",
            "reference_sha256": "r",
            "job": {"variant": "adapted" if actual else "base"},
        }
        return audit(profile, receipt, {"max_new_tokens": 1000})

    def test_base_profile_can_record_unused_adapter_provenance(self):
        self.assertTrue(self.run_case(False, False)["configuration_consistent"])

    def test_unexpected_actual_adapter_is_failure(self):
        self.assertFalse(self.run_case(False, True)["configuration_consistent"])

    def test_contradictory_recipe_fields_are_failure(self):
        self.assertFalse(self.run_case(False, False, True)["configuration_consistent"])


if __name__ == "__main__":
    unittest.main()
