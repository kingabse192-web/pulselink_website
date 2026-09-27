#!/usr/bin/env python3
"""Run PulseLink behind an HTTPS Cloudflare quick tunnel.

Requires the cloudflared executable to be installed and available on PATH.
The generated trycloudflare.com URL is injected as PULSELINK_PUBLIC_BASE_URL,
so links created from the dashboard use the public URL rather than localhost.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = os.environ.get("PORT", "5000")
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)


def main() -> int:
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        print("cloudflared was not found on PATH.")
        print("Install cloudflared, then run this script again.")
        return 1

    tunnel = subprocess.Popen(
        [cloudflared, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    public_url = None
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            line = tunnel.stdout.readline() if tunnel.stdout else ""
            if line:
                print("[cloudflared]", line.rstrip())
                match = URL_RE.search(line)
                if match:
                    public_url = match.group(0)
                    break
            elif tunnel.poll() is not None:
                break

        if not public_url:
            print("Could not obtain a public HTTPS tunnel URL.")
            return 1

        env = os.environ.copy()
        env["PULSELINK_PUBLIC_BASE_URL"] = public_url
        print("\nPulseLink public URL:")
        print(public_url)
        print("\nShare tracking links generated from this URL with your friend.")
        print("Keep this terminal and the PulseLink process running while the link is in use.\n")

        app_proc = subprocess.Popen(
            [sys.executable, str(ROOT / "app.py")],
            cwd=ROOT,
            env=env,
        )
        try:
            return app_proc.wait()
        finally:
            if app_proc.poll() is None:
                app_proc.terminate()
    except KeyboardInterrupt:
        return 130
    finally:
        if tunnel.poll() is None:
            tunnel.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
