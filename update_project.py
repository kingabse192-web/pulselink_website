#!/usr/bin/env python3
"""
Safe PulseLink startup updater.

When PulseLink is started from a clean Git clone, this script checks origin/main.
If origin/main is ahead and the working tree is clean, it performs only a
fast-forward pull. It never overwrites uncommitted local work.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REMOTE = os.environ.get("PULSELINK_UPDATE_REMOTE", "origin")
BRANCH = os.environ.get("PULSELINK_UPDATE_BRANCH", "main")


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def update_project() -> bool:
    if os.environ.get("PULSELINK_AUTO_UPDATE", "1").strip().lower() in {"0", "false", "no", "off"}:
        print("PulseLink auto-update: disabled.")
        return False

    if not (ROOT / ".git").exists():
        print("PulseLink auto-update: skipped (this copy is not a Git clone).")
        return False

    clean = run("git", "status", "--porcelain")
    if clean.returncode != 0:
        print("PulseLink auto-update: skipped (Git status could not be checked).")
        return False
    if clean.stdout.strip():
        print("PulseLink auto-update: skipped (local changes are present).")
        return False

    fetch = run("git", "fetch", REMOTE, BRANCH, "--quiet")
    if fetch.returncode != 0:
        print("PulseLink auto-update: could not reach the Git remote; starting current code.")
        return False

    current = run("git", "rev-parse", "HEAD")
    remote = run("git", "rev-parse", f"{REMOTE}/{BRANCH}")
    if current.returncode != 0 or remote.returncode != 0:
        print("PulseLink auto-update: could not compare revisions.")
        return False

    if current.stdout.strip() == remote.stdout.strip():
        print("PulseLink auto-update: already up to date.")
        return False

    ancestor = run("git", "merge-base", "--is-ancestor", "HEAD", f"{REMOTE}/{BRANCH}")
    if ancestor.returncode != 0:
        print("PulseLink auto-update: local branch is not a fast-forward of remote; starting current code.")
        return False

    pull = run("git", "pull", "--ff-only", REMOTE, BRANCH)
    if pull.returncode != 0:
        print("PulseLink auto-update: fast-forward failed; starting current code.")
        if pull.stderr:
            print(pull.stderr.strip())
        return False

    print("PulseLink auto-update: project updated from GitHub.")
    return True


if __name__ == "__main__":
    raise SystemExit(10 if update_project() else 0)
