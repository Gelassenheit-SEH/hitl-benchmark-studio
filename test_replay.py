"""Recorded trace serving is optional and stays separate from the practice workflow."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import server


class ReplayRoutes(unittest.TestCase):
    def open_server(self, path):
        service = server.StudioServer(0, replay_path=path)
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(service.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(service.shutdown)
        return f"http://127.0.0.1:{service.server_port}"

    def test_without_local_data_root_is_editable_demo(self):
        with tempfile.TemporaryDirectory() as directory:
            base = self.open_server(Path(directory) / "missing.json")
            with urlopen(base, timeout=3) as result:
                self.assertIn(b"Batch plan", result.read())
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/api/replays", timeout=3)
            self.assertEqual(404, error.exception.code)

    def test_with_local_data_root_plays_back_records_and_practice_still_opens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recorded.json"
            expected = {"cases": [{"id": "Replay 1", "steps": [{"action": "released"}]}]}
            path.write_text(json.dumps(expected), encoding="utf-8")
            base = self.open_server(path)
            with urlopen(base, timeout=3) as result:
                self.assertIn(b"Recorded cases", result.read())
            with urlopen(base + "/api/replays", timeout=3) as result:
                self.assertEqual(expected, json.load(result))
            with urlopen(base + "/practice", timeout=3) as result:
                self.assertIn(b"Batch plan", result.read())
