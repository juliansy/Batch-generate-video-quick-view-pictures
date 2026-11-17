"""Prove the gate fails when the things it claims to catch actually break."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run_gate(root: Path) -> tuple[int, str]:
    result = subprocess.run(
        [PY, str(root / "tools/release_check.py"), "--root", str(root), "--skip-tests"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.returncode, result.stdout


def experiment(name: str, mutate) -> None:
    temp = Path(tempfile.mkdtemp(prefix="qvp-gate-"))
    try:
        work = temp / "repo"
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.zip"))
        mutate(work)
        code, output = run_gate(work)
        failed = [line.split()[1] for line in output.splitlines() if line.startswith("[FAIL]")]
        print(f"{name:<28} exit={code}  failed={sorted(set(failed))}")
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


experiment("clean copy", lambda work: None)
CURRENT = re.search(r'^VERSION = "([0-9][0-9.]*)"', (ROOT / "qvp.py").read_text(encoding="utf-8"), re.M).group(1)
experiment("version drift", lambda work: edit(work / "qvp.py", f'VERSION = "{CURRENT}"', 'VERSION = "9.9.9"'))
experiment("stale README sample", lambda work: edit(work / "README.md", f"qvp {CURRENT}", "qvp 1.0.0"))


def lf_bat(work: Path) -> None:
    data = (work / "qvp.bat").read_bytes().replace(b"\r\n", b"\n")
    (work / "qvp.bat").write_bytes(data)


experiment("bat rewritten as LF", lf_bat)
experiment("undocumented flag", lambda work: edit(work / "README.md", "| `--quality 1-100` | 82 jpeg / 60 avif | encoder quality |\n", ""))
experiment("internal voice", lambda work: edit(work / "README.md", "## Limitations", "本机实测结果如下。\n\n## Limitations"))
experiment("private path", lambda work: edit(work / "README.md", "## Limitations", "Tested on D:\\Download\\clips.\n\n## Limitations"))
def swap_zh_sections(work: Path) -> None:
    path = work / "README.zh-CN.md"
    text = path.read_text(encoding="utf-8")
    layout_at = text.index("## 目录长什么样")
    options_at = text.index("## 需要什么")
    head, layout, options = text[:layout_at], text[layout_at:options_at], text[options_at:]
    path.write_text(head + options + layout, encoding="utf-8", newline="\n")


experiment("zh sections swapped", swap_zh_sections)
