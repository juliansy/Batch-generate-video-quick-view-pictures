#!/usr/bin/env python3
"""Pre-release gate for video-quick-view.

Run it before every tag. Every check here exists because that exact thing
shipped wrong at least once:

  V1-V5  a version string that disagreed with another version string
  T1-T2  a test count in the docs that was four reviews out of date
  F1     a flag documented after it had been deleted (--hwaccel)
  H1     README and README.zh-CN.md drifting apart
  I1     notes written for the two of us while the repo was public
  P1     a real clip title and a local path inside a published file
  N1-N2  a launcher that turned out to be LF after a patch script touched it
  K1     a changelog that skipped a version and documented one that never shipped

Usage:
    python tools/release_check.py            # working tree
    python tools/release_check.py --package video-quick-view-X.Y.Z.zip
    python tools/release_check.py --skip-tests   # docs-only pass

Exit code 0 = every check passed, 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW = ROOT / "tools" / "release_allow.txt"

PUBLIC_DOCS = [
    "README.md",
    "README.zh-CN.md",
    "CHANGELOG.md",
    "docs/06-auto-grid.md",
    "docs/07-performance.md",
    "docs/08-release.md",
    "qvp.bat",
]

# Wording that only makes sense if you are the author talking to themselves.
INTERNAL_VOICE = [
    "本机", "我们", "咱们", "这台机器", "特调", "作者",
    "our machine", "on my machine", "this machine", "as we discussed",
    "for the author", "TODO", "FIXME", "XXX",
]

# Things that must never be published: personal paths and real clip titles.
# D:\Videos is the documented placeholder, everything else under D:\ is real.
PRIVATE = [
    r"D:\\(?!Videos)", r"C:\\Users", r"/home/", r"/Users/",
    "Kalinka", "Калинка", "BLACKPINK", "Zingy", "Rockettes",
    "Gardetanz", "Irish dance", "Arctic Fox", "戴维",
]

REQUIRED = [
    "qvp.py", "qvp.bat", "README.md", "README.zh-CN.md", "CHANGELOG.md",
    "LICENSE", "requirements.txt",
    "docs/06-auto-grid.md", "docs/07-performance.md", "docs/08-release.md",
]

# Only a checkout has these; the release archive deliberately does not.
REPO_ONLY = [".gitignore", ".gitattributes"]

@dataclass
class Finding:
    level: str  # PASS / WARN / FAIL
    code: str
    message: str


class Gate:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.is_repo = (root / ".git").exists()
        self.findings: list[Finding] = []
        self.tests_ran: int | None = None
        self.version = ""

    # -- helpers ---------------------------------------------------------
    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def add(self, level: str, code: str, message: str) -> None:
        self.findings.append(Finding(level, code, message))

    def run(self, *command: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            list(command), cwd=str(cwd or self.root), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )

    def allowed(self, path: str, phrase: str) -> str | None:
        if not ALLOW.exists():
            return None
        for line in ALLOW.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            if parts[0].strip() == path and parts[1].strip() == phrase:
                return parts[2].strip() if len(parts) > 2 else ""
        return None

    # -- V: versions -----------------------------------------------------
    def check_version(self) -> None:
        match = re.search(r'^VERSION = "([0-9][0-9.]*)"', self.read("qvp.py"), re.M)
        if not match:
            self.add("FAIL", "V1", "qvp.py has no VERSION constant")
            return
        self.version = match.group(1)
        self.add("PASS", "V1", f"qvp.py says {self.version}")

        printed = self.run(sys.executable, "qvp.py", "--version").stdout.strip()
        if printed == f"qvp {self.version}":
            self.add("PASS", "V2", f"--version prints {printed}")
        else:
            self.add("FAIL", "V2", f"--version prints {printed!r}, expected 'qvp {self.version}'")

        for name in ("README.md", "README.zh-CN.md"):
            sample = re.search(r"```text\n(qvp [0-9][0-9.]*)\n", self.read(name))
            if not sample:
                self.add("FAIL", "V3", f"{name} has no sample transcript starting with 'qvp X.Y.Z'")
            elif sample.group(1) != f"qvp {self.version}":
                self.add("FAIL", "V3", f"{name} sample says {sample.group(1)!r}, binary says qvp {self.version}")
            else:
                self.add("PASS", "V3", f"{name} sample matches the binary")

        heading = re.search(r"^## v([0-9][0-9.]*)", self.read("CHANGELOG.md"), re.M)
        if not heading:
            self.add("FAIL", "V4", "CHANGELOG.md has no '## vX.Y.Z' entry")
        elif heading.group(1) != self.version:
            self.add("FAIL", "V4", f"CHANGELOG.md starts at v{heading.group(1)}, binary is {self.version}")
        else:
            self.add("PASS", "V4", f"CHANGELOG.md starts at v{self.version}")

    # -- T: test count ---------------------------------------------------
    def check_tests(self, skip: bool) -> None:
        if skip:
            self.add("WARN", "T1", "test run skipped (--skip-tests)")
            return
        result = self.run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q")
        match = re.search(r"Ran (\d+) tests?", result.stderr + result.stdout)
        if not match:
            self.add("FAIL", "T1", "could not read the number of tests from unittest")
            return
        self.tests_ran = int(match.group(1))
        if result.returncode == 0:
            self.add("PASS", "T1", f"{self.tests_ran} tests pass")
        else:
            self.add("FAIL", "T1", f"tests fail (exit {result.returncode}); run them yourself")

        # docs/01-docs/05 are records of the v1->v2 rewrite, bannered as such:
        # their counts describe that period, so only current docs are checked.
        claimed: list[tuple[str, int]] = []
        for name in PUBLIC_DOCS:
            path = self.root / name
            if not path.exists():
                continue
            for match in re.finditer(r"(\d+)\s*(?:个用例|tests)", self.read(name)):
                claimed.append((name, int(match.group(1))))
        stale = [(name, count) for name, count in claimed if count != self.tests_ran]
        if stale:
            listing = ", ".join(f"{name} says {count}" for name, count in stale)
            self.add("FAIL", "T2", f"{listing}; the suite ran {self.tests_ran}")
        else:
            self.add("PASS", "T2", "every current test count matches the suite")

    # -- F: documented flags ---------------------------------------------
    def check_flags(self) -> None:
        source = self.read("qvp.py")
        found: set[str] = set()
        for chunk in source.split("add_argument(")[1:]:
            head = chunk.split(")", 1)[0]
            found.update(re.findall(r'"(-{1,2}[A-Za-z][A-Za-z0-9-]*)"', head))
        found.discard("-h")
        found.discard("--help")

        documented: set[str] = set()
        for line in self.read("README.md").splitlines():
            if line.startswith("| `"):
                documented.update(re.findall(r"(-{1,2}[A-Za-z][A-Za-z0-9-]*)", line.split("|")[1]))

        missing = sorted(flag for flag in found if flag not in documented)
        extra = sorted(flag for flag in documented if flag not in found)
        if missing:
            self.add("FAIL", "F1", f"flags in the parser but missing from the README table: {missing}")
        if extra:
            self.add("FAIL", "F1", f"flags in the README table but not in the parser: {extra}")
        if not missing and not extra:
            self.add("PASS", "F1", f"{len(found)} flags, documented and implemented")

    # -- H: bilingual parity ---------------------------------------------
    def sections(self, name: str) -> list[tuple[str, str]]:
        """[(heading, first inline code / flag token in that section)]."""
        text = self.read(name)
        parts = re.split(r"(?m)^(#{2,3}) (.+)$", text)
        result: list[tuple[str, str]] = []
        for index in range(1, len(parts), 3):
            level, heading, body = parts[index], parts[index + 1], parts[index + 2]
            flag = re.search(r"(--[a-z][a-z-]+)", body)
            inline = re.search(r"`([^`\n]+)`", body)
            token = flag.group(1) if flag else (inline.group(1) if inline else "")
            result.append((f"{len(level)}:{heading.strip()}", token))
        return result

    def check_headings(self) -> None:
        english = self.sections("README.md")
        chinese = self.sections("README.zh-CN.md")
        if len(english) != len(chinese):
            self.add("FAIL", "H1", f"{len(english)} sections in English, {len(chinese)} in Chinese")
            return
        mismatched = [
            f"line {index + 1}: {en[0]!r} vs {zh[0]!r}"
            for index, (en, zh) in enumerate(zip(english, chinese))
            if en[0].split(":")[0] != zh[0].split(":")[0]
        ]
        if mismatched:
            self.add("FAIL", "H1", "heading levels differ: " + "; ".join(mismatched))
        else:
            self.add("PASS", "H1", f"{len(english)} sections, same order and level in both languages")

        # Same heading count is not enough: a section can be renamed, moved or
        # merged in one language and the counts still line up. Compare the first
        # inline token of each section - a flag, a file name, a value - which
        # is language-independent.
        drifted = [
            f"section {index + 1} ({en[0]}): {en[1]!r} vs {zh[1]!r}"
            for index, (en, zh) in enumerate(zip(english, chinese))
            if en[1] and zh[1] and en[1].lower() != zh[1].lower()
        ]
        if drifted:
            self.add("FAIL", "H2", "the two READMEs cover different things: " + "; ".join(drifted))
        else:
            tokens = sum(1 for en, zh in zip(english, chinese) if en[1] and zh[1])
            self.add("PASS", "H2", f"{tokens} sections start with the same token in both languages")

    # -- I / P: voice and privacy ---------------------------------------
    def check_wording(self) -> None:
        voice_hits: list[str] = []
        private_hits: list[str] = []
        for name in PUBLIC_DOCS:
            path = self.root / name
            if not path.exists():
                continue
            text = self.read(name)
            for phrase in INTERNAL_VOICE:
                if phrase in text and not self.allowed(name, phrase):
                    voice_hits.append(f"{name}: {phrase!r}")
            for pattern in PRIVATE:
                if re.search(pattern, text):
                    private_hits.append(f"{name}: /{pattern}/")
        if voice_hits:
            self.add("FAIL", "I1", "text written for the author, not the reader: " + "; ".join(voice_hits))
        else:
            self.add("PASS", "I1", "no internal voice in the public docs")
        if private_hits:
            self.add("FAIL", "P1", "private paths or clip titles: " + "; ".join(private_hits))
        else:
            self.add("PASS", "P1", "no local paths or real clip titles in the public docs")

    # -- N: files and line endings ---------------------------------------
    def check_files(self) -> None:
        required = REQUIRED + (REPO_ONLY if self.is_repo else [])
        missing = [name for name in required if not (self.root / name).exists()]
        if missing:
            self.add("FAIL", "N3", f"missing files: {missing}")
        else:
            self.add("PASS", "N3", f"{len(required)} required files present")

        problems: list[str] = []
        for pattern, want_crlf in (("*.py", False), ("*.bat", True), ("*.md", False)):
            for path in sorted(self.root.rglob(pattern)):
                if ".git" in path.parts or "build" in path.parts:
                    continue
                data = path.read_bytes()
                crlf = data.count(b"\r\n")
                bare = data.count(b"\n") - crlf
                if want_crlf and bare:
                    problems.append(f"{path.relative_to(self.root)} has {bare} bare LF (needs CRLF)")
                if not want_crlf and crlf:
                    problems.append(f"{path.relative_to(self.root)} has {crlf} CRLF (needs LF)")
        if problems:
            self.add("FAIL", "N1", "; ".join(problems))
        else:
            self.add("PASS", "N1", "line endings match the .gitattributes rules")

    # -- K: changelog and tags -------------------------------------------
    def check_changelog(self) -> None:
        entries = [match.group(1) for match in re.finditer(r"(?m)^## v([0-9][0-9.]*)", self.read("CHANGELOG.md"))]
        if not self.is_repo:
            self.add("WARN", "K1", "no .git here (running from an archive) - tag checks skipped")
            return
        tags = [tag.lstrip("v") for tag in self.run("git", "tag", "--list", "v*").stdout.split()]
        if self.version and self.version not in tags:
            self.add("WARN", "K1", f"v{self.version} has no tag yet (create it with the release, before announcing)")
        untagged = [version for version in entries if version not in tags and version != self.version]
        if untagged:
            self.add(
                "WARN",
                "K1",
                f"{len(untagged)} older entries predate the history rebuild and have no tag: {untagged}",
            )
        undocumented = [tag for tag in tags if tag not in entries]
        if undocumented:
            self.add("FAIL", "K2", f"tags with no changelog entry: {undocumented}")
        if not undocumented:
            self.add("PASS", "K2", f"all {len(tags)} tags have a changelog entry")

    # -- package ---------------------------------------------------------
    def check_package(self, package: Path) -> None:
        if not package.exists():
            self.add("FAIL", "N2", f"package not found: {package}")
            return
        with tempfile.TemporaryDirectory(prefix="qvp-pkg-") as temp:
            with zipfile.ZipFile(package) as archive:
                archive.extractall(temp)
                names = archive.namelist()
            roots = {name.split("/")[0] for name in names if name.split("/")[0]}
            if len(roots) != 1:
                self.add("FAIL", "N2", f"archive should hold exactly one top folder, found {sorted(roots)}")
                return
            top = Path(temp) / roots.pop()

            bat = (top / "qvp.bat").read_bytes()
            bare = bat.count(b"\n") - bat.count(b"\r\n")
            if bare:
                self.add("FAIL", "N2", f"qvp.bat inside the package has {bare} bare LF")
            else:
                self.add("PASS", "N2", "qvp.bat inside the package is CRLF")

            readme = (top / "README.md").read_text(encoding="utf-8")
            sample = re.search(r"```text\n(qvp [0-9][0-9.]*)\n", readme)
            expected = f"qvp {self.version}"
            if sample and sample.group(1) == expected:
                self.add("PASS", "V5", "packaged README sample matches the version")
            else:
                self.add("FAIL", "V5", f"packaged README sample says {sample.group(1) if sample else None!r}")

            for name in ("docs/08-release.md", "tests/test_qvp.py", "qvp.py"):
                if not (top / name).exists():
                    self.add("FAIL", "N2", f"package is missing {name}")
            version = self.run(sys.executable, "qvp.py", "--version", cwd=top).stdout.strip()
            if version == expected:
                self.add("PASS", "N2", f"packaged qvp.py prints {version}")
            else:
                self.add("FAIL", "N2", f"packaged qvp.py prints {version!r}, expected {expected!r}")

    # -- driver ----------------------------------------------------------
    def execute(self, args) -> int:
        self.check_version()
        self.check_tests(args.skip_tests)
        self.check_flags()
        self.check_headings()
        self.check_wording()
        self.check_files()
        self.check_changelog()
        if args.package:
            self.check_package(Path(args.package))

        width = max(len(item.code) for item in self.findings)
        for item in self.findings:
            mark = {"PASS": "ok  ", "WARN": "warn", "FAIL": "FAIL"}[item.level]
            print(f"[{mark}] {item.code:<{width}}  {item.message}")
        failed = [item for item in self.findings if item.level == "FAIL"]
        warned = [item for item in self.findings if item.level == "WARN"]
        print()
        print(f"{len(self.findings) - len(failed) - len(warned)} passed, {len(warned)} warnings, {len(failed)} failures")
        if failed:
            print("Fix the failures before tagging. A green suite is not a release.")
            return 1
        if warned:
            print("Warnings only - decide about each one, do not just ignore them.")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-release gate for video-quick-view")
    parser.add_argument("--package", help="also inspect this release zip")
    parser.add_argument("--skip-tests", action="store_true", help="docs-only pass (no unittest run)")
    parser.add_argument("--root", default=str(ROOT), help="repository root (default: this checkout)")
    args = parser.parse_args(argv)
    return Gate(Path(args.root)).execute(args)


if __name__ == "__main__":
    sys.exit(main())
