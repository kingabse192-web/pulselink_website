#!/usr/bin/env python3
"""Start PulseLink with an optional safe GitHub fast-forward update first."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

subprocess.run([sys.executable, str(ROOT / "update_project.py")], cwd=ROOT, check=False)

if os.environ.get("PULSELINK_PRODUCTION", "").strip().lower() in {"1", "true", "yes", "on"}:
    port = os.environ.get("PORT", "5000")
    os.execv(
        sys.executable,
        [sys.executable, "-m", "gunicorn", "--bind", f"0.0.0.0:{port}", "app:app"],
    )

os.execv(sys.executable, [sys.executable, str(ROOT / "app.py")])
