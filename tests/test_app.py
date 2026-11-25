import base64
import json
import re
import tempfile
import unittest
import zlib
from pathlib import Path

import app


APP_DIR = Path(__file__).resolve().parents[1]
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\w)")


class AppBundleTests(unittest.TestCase):
    def test_bundle_includes_public_data_and_not_rma_records(self):
        data = {"devices": [{"name": "Sample device"}]}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text(
                f"<html><body>{app.BOOTSTRAP_MARKER}</body></html>", encoding="utf-8"
            )
            (root / "data.json").write_text(json.dumps(data), encoding="utf-8")

            html = app.build_authenticated_html(root)

        match = re.search(r"const compressed = Uint8Array\.from\(atob\('([^']+)'", html)
        self.assertIsNotNone(match)
        compressed = base64.b64decode(match.group(1))
        bundle = json.loads(zlib.decompress(compressed))
        self.assertEqual(json.loads(bundle["files"]["data.json"]), data)
        self.assertNotIn("rma", bundle["files"])
        self.assertNotIn("rma/cases.json", html)
        self.assertIn("window.__lgRmaUnavailable = true;", html)

    def test_public_copy_disables_lookup_and_omits_private_files(self):
        html = (APP_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("window.__lgRmaUnavailable = true", html)
        self.assertIn("RMA lookup is disabled in this public-safe copy", html)
        self.assertFalse((APP_DIR / "rma").exists())
        self.assertFalse((APP_DIR / ".streamlit" / "secrets.toml").exists())

    def test_public_data_has_no_email_or_phone_patterns(self):
        data = json.loads((APP_DIR / "data.json").read_text(encoding="utf-8"))
        serialized = json.dumps(data)
        self.assertIsNone(EMAIL_PATTERN.search(serialized))
        self.assertIsNone(PHONE_PATTERN.search(serialized))

    def test_rejects_image_paths_outside_public_image_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text(
                f"<html><body>{app.BOOTSTRAP_MARKER}</body></html>", encoding="utf-8"
            )
            (root / "data.json").write_text(
                json.dumps({"images": ["img/../../outside.png"]}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                app.build_authenticated_html(root)


if __name__ == "__main__":
    unittest.main()
