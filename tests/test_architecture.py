"""Non-regression tests for DomoLink-Mistral integration."""
import os
import sys
import unittest
from unittest.mock import MagicMock

# Add component to path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from tests.ha_mock import setup_ha_mock

setup_ha_mock()

import voluptuous as vol
from custom_components.domolink_mistral.__init__ import (
    APPLY_FIX_SCHEMA,
    ISSUE_ID_SCHEMA,
    GENERATE_AUTOMATION_SCHEMA,
    ANALYZE_IMAGE_SCHEMA,
    DAILY_BRIEFING_SCHEMA,
    SCHEMA_EMPTY,
)
from custom_components.domolink_mistral.mistral_api import (
    _extract_mistral_error_message,
    _format_mistral_http_error,
)


class TestDomolinkMistralArchitecture(unittest.TestCase):
    """Test architecture, service schemas and Mistral error parsing."""

    def test_admin_service_schemas_allow_extra(self):
        """Ensure all service schemas permit extra keys (preventing HA 2024.10+ rejection)."""
        extra_data = {"extra_ha_option": True, "caller": "frontend_unit_test"}

        # Empty schema
        valid_empty = SCHEMA_EMPTY(extra_data)
        self.assertIn("extra_ha_option", valid_empty)

        # Issue ID schema
        valid_issue = ISSUE_ID_SCHEMA({"issue_id": "test_1", **extra_data})
        self.assertEqual(valid_issue["issue_id"], "test_1")
        self.assertTrue(valid_issue["extra_ha_option"])

        # Generate automation schema
        valid_gen = GENERATE_AUTOMATION_SCHEMA({"prompt": "allume le salon", **extra_data})
        self.assertEqual(valid_gen["prompt"], "allume le salon")

        # Analyze image schema
        valid_img = ANALYZE_IMAGE_SCHEMA({"prompt": "que vois-tu?", **extra_data})
        self.assertEqual(valid_img["prompt"], "que vois-tu?")

        # Daily briefing schema
        valid_brief = DAILY_BRIEFING_SCHEMA({"time_of_day": "morning", **extra_data})
        self.assertEqual(valid_brief["time_of_day"], "morning")

    def test_extract_mistral_error_message_variations(self):
        """Verify error extraction from different Mistral API error response shapes."""
        # 1. Standard "message"
        res1 = _extract_mistral_error_message({"message": "Invalid API key"})
        self.assertEqual(res1, "Invalid API key")

        # 2. String "detail"
        res2 = _extract_mistral_error_message({"detail": "Model deprecated"})
        self.assertEqual(res2, "Model deprecated")

        # 3. List of validation error dicts (FastAPI / Pydantic)
        res3 = _extract_mistral_error_message({
            "detail": [
                {"loc": ["body", "model"], "msg": "value is not a valid enumeration member"},
                {"loc": ["body", "temperature"], "msg": "must be <= 1.0"}
            ]
        })
        self.assertIn("value is not a valid enumeration member", res3)
        self.assertIn("body -> model", res3)

        # 4. Nested "error" dict
        res4 = _extract_mistral_error_message({"error": {"message": "Rate limit exceeded"}})
        self.assertEqual(res4, "Rate limit exceeded")

        # 5. Fallback
        res5 = _extract_mistral_error_message({}, fallback="Fallback Bad Request")
        self.assertEqual(res5, "Fallback Bad Request")

    def test_format_mistral_http_error(self):
        """Verify formatted error messages and classifications for Mistral HTTP status codes."""
        err400 = _format_mistral_http_error(400, "Invalid model name")
        self.assertEqual(err400["type"], "bad_request")
        self.assertIn("HTTP 400", err400["user_msg"])
        self.assertIn("Invalid model name", err400["user_msg"])

        err401 = _format_mistral_http_error(401, "Unauthorized")
        self.assertEqual(err401["type"], "auth_error")
        self.assertIn("HTTP 401", err401["user_msg"])

        err429 = _format_mistral_http_error(429, "Too Many Requests")
        self.assertEqual(err429["type"], "rate_limit")
        self.assertIn("HTTP 429", err429["user_msg"])

    def test_manifest_requirements_and_version(self):
        """Ensure manifest.json is well-formed with domain and version."""
        import json
        manifest_path = os.path.join(ROOT_DIR, "custom_components", "domolink_mistral", "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertEqual(manifest.get("domain"), "domolink_mistral")
        self.assertEqual(manifest.get("version"), "3.0.1")
        self.assertIn("codeowners", manifest)


if __name__ == "__main__":
    unittest.main()
