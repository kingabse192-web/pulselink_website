#!/usr/bin/env python3
"""Start PulseLink.

app.py performs the automatic GitHub fast-forward check itself when launched
as a script, so this wrapper simply launches it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.execv(sys.executable, [sys.executable, str(ROOT / "app.py")])
