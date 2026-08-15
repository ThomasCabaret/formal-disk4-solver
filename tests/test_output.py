from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from formal_disk4.pipeline.output import atomic_write_json


class AtomicOutputTests(unittest.TestCase):
    def test_atomic_json_retries_transient_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "report.json"
            path.write_text('{"old": true}\n', encoding="utf-8")
            real_replace = os.replace
            attempts = 0

            def flaky_replace(source: object, target: object) -> None:
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("transient Windows share lock")
                real_replace(source, target)

            with patch(
                "formal_disk4.pipeline.output.os.replace",
                side_effect=flaky_replace,
            ), patch("formal_disk4.pipeline.output.time.sleep") as sleep:
                atomic_write_json(path, {"generation": 623})

            self.assertEqual(attempts, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"generation": 623},
            )
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
