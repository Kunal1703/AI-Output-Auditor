"""Pytest bootstrap — makes the ``app`` package importable from the tests.

The AI Output Auditor's shared-service unit tests (``tests/unit``) are
self-contained and use only pytest built-ins; this file only ensures the backend
package root is on ``sys.path`` when pytest runs from the repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
