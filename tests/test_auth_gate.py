import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class AuthGateTests(unittest.TestCase):
    def test_app_stops_at_login_before_rendering_the_hub(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

        self.assertFalse(app.exception, app.exception)
        self.assertEqual(app.title[0].value, "🔒 LG RMA login")
        self.assertEqual(len(app.button), 1)
        self.assertEqual(app.button[0].label, "Send verification code")


if __name__ == "__main__":
    unittest.main()
