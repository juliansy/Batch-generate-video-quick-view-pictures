#!/usr/bin/env python3
"""Build the release zip, then hand it to the release gate.

The point is not to save typing. Twice a release shipped a file that the
working tree had in one state and the archive in another - once a `qvp.bat`
that a patch script had rewritten with LF line endings. So this script:

  1. refuses to build if `qvp.bat` is not pure CRLF (it does not "fix" it -
     a tool that silently repairs text is how the LF archive happened),
  2. packs an explicit file list, so a new docs page cannot be forgotten,
  3. runs tools/release_check.py --package on the result.

Usage:
    python tools/make_package.py [--keep]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = [
    "qvp.py",
    "qvp.bat",
    "README.md",
    "README.zh-CN.md",
    "CHANGELOG.md",
    "LICENSE",
    "requirements.txt",
]
TREES = ["docs", "tests", "tools"]


def version() -> str:
    for line in (ROOT / "qvp.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("qvp.py has no VERSION constant")


def check_bat() -> None:
    data = (ROOT / "qvp.bat").read_bytes()
    bare = data.count(b"\n") - data.count(b"\r\n")
    if bare:
        raise SystemExit(
            f"qvp.bat has {bare} bare LF - the release archive would ship a broken launcher.\n"
            "Fix the file (CRLF, no BOM) and run this again. This script does not rewrite it for you."
        )


def build(tag: str, keep: bool) -> Path:
    target = ROOT.parent / f"video-quick-view-{tag}.zip"
    staging = Path(tempfile.mkdtemp(prefix="qvp-pack-"))
    try:
        top = staging / f"video-quick-view-{tag}"
        (top / "docs").mkdir(parents=True)
        (top / "tests").mkdir()
        (top / "tools").mkdir()
        for name in FILES:
            shutil.copy2(ROOT / name, top / name)
        for tree in TREES:
            for source in sorted((ROOT / tree).glob("*")):
                if source.is_file() and source.suffix in {".md", ".py"}:
                    shutil.copy2(source, top / tree / source.name)
        if target.exists():
            target.unlink()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(top.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging).as_posix())
        print(f"built {target} ({target.stat().st_size:,} bytes)")
        return target
    finally:
        if not keep:
            shutil.rmtree(staging, ignore_errors=True)


def gate(package: Path) -> int:
    command = [sys.executable, str(ROOT / "tools" / "release_check.py"), "--package", str(package)]
    print("$ " + " ".join(command))
    return subprocess.call(command, cwd=str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and check the release archive")
    parser.add_argument("--keep", action="store_true", help="keep the staging tree for inspection")
    parser.add_argument("--skip-gate", action="store_true", help="build only (never for a real release)")
    args = parser.parse_args(argv)

    check_bat()
    package = build(version(), args.keep)
    if args.skip_gate:
        print("gate skipped - do not publish this archive")
        return 0
    return gate(package)


if __name__ == "__main__":
    sys.exit(main())
