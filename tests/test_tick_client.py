"""
Tick 客户端集成测试（unittest 版本，无需 pytest）。
"""

from __future__ import annotations

import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestTickClient(unittest.TestCase):
    def test_get_best_tick_000300_shape(self):
        from tick_client import get_best_tick

        result = get_best_tick("000300", config_path=str(ROOT / "config" / "environments" / "base.yaml"))

        self.assertIn("ok", result)
        self.assertIn("tick", result)
        self.assertIn("provider", result)
        self.assertIn("error", result)

        # 如果网络/接口异常，至少要给出 error 字符串，便于排查
        if not result["ok"]:
            self.assertTrue(isinstance(result["error"], str) and len(result["error"]) > 0)
            return

        tick = result["tick"]
        self.assertIsInstance(tick, dict)
        self.assertIn("last", tick)
        self.assertIn("timestamp", tick)


if __name__ == "__main__":
    unittest.main()

