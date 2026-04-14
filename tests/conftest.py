"""确保 pytest 可从项目根导入 plugins / src。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PLUGINS = _ROOT / "plugins"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if _PLUGINS.exists() and str(_PLUGINS) not in sys.path:
    sys.path.insert(0, str(_PLUGINS))
