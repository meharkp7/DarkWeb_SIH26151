"""Security scanning entrypoint used by CI.

Modes:
    --deps     query the OSV database for vulnerable installed distributions
    --secrets  scan tracked files for committed credentials

Both modes exit non-zero when findings are reported at ERROR severity.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "artifacts",
    "reports",
}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".whl", ".lock"}

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key-block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "generic-secret-assignment",
        re.compile(
            r"(?i)\b(password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*(?!settings\.|os\.|config\.|env\.)[\"']?[^\s\"']{12,}"
        ),
    ),
    # `\b` will not match inside SCREAMING_SNAKE_CASE identifiers because `_`
    # is a word character, so AWS_SECRET_ACCESS_KEY = "..." slips past the
    # pattern above. This variant requires an upper-case identifier holding a
    # quoted value, which is how env-var secrets are actually written. It
    # stays deliberately narrow: a looser version also matched ordinary code
    # such as `tokens = Counter()`.
    (
        "env-var-secret-assignment",
        re.compile(
            r"(?:^|[^A-Za-z0-9_])[A-Z0-9_]*"
            r"(?:PASSWORD|PASSWD|SECRET|API_?KEY|TOKEN|CREDENTIALS?)"
            r"[A-Z0-9_]*\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']"
        ),
    ),
)

ALLOWLIST_MARKERS = ("example", "placeholder", "changeme", "your-", "xxx", "dummy")


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    location: str
    detail: str


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return [p for p in REPO_ROOT.rglob("*") if p.is_file()]

    files = [REPO_ROOT / line for line in out.splitlines() if line]
    return [p for p in files if p.is_file()]


def scan_secrets() -> list[Finding]:
    findings: list[Finding] = []
    for path in _tracked_files():
        if path.suffix in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if any(marker in lowered for marker in ALLOWLIST_MARKERS):
                continue
            for name, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        Finding(
                            severity="ERROR",
                            category=name,
                            location=f"{path.relative_to(REPO_ROOT)}:{line_no}",
                            detail=line.strip()[:120],
                        )
                    )
    return findings


def _installed_distributions() -> list[tuple[str, str]]:
    """``(name, version)`` for every installed distribution, name lowercased.

    Uses ``importlib.metadata`` rather than shelling out to ``pip``: this
    project is managed by uv, whose environments do not ship pip, so
    ``python -m pip list`` always failed and the dependency scan silently
    skipped itself — reporting a warning and exiting 0 on every run.
    """
    from importlib.metadata import distributions

    found: dict[str, str] = {}
    for dist in distributions():
        name = (dist.metadata["Name"] or "").strip().lower()
        if name:
            found[name] = dist.version or ""
    return sorted(found.items())


def scan_dependencies() -> list[Finding]:
    """Query OSV for known vulnerabilities in installed distributions."""
    try:
        import httpx
    except ImportError:
        return [Finding("WARN", "deps", "-", "httpx unavailable; dependency scan skipped")]

    installed = _installed_distributions()
    if not installed:
        return [
            Finding(
                "ERROR",
                "deps",
                "-",
                "no installed distributions found; dependency scan did not run",
            )
        ]

    findings: list[Finding] = []
    try:
        # The version is included so OSV only returns advisories that actually
        # affect the installed release. Omitting it returns every advisory ever
        # published for the name (SQLAlchemy's 2012 PYSEC entries, for example),
        # which buries real findings under decades of already-fixed history and
        # trains reviewers to ignore this gate.
        response = httpx.post(
            "https://api.osv.dev/v1/querybatch",
            json={
                "queries": [
                    {"package": {"name": n, "ecosystem": "PyPI"}, "version": v or None}
                    for n, v in installed
                ]
            },
            timeout=30.0,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        # A scan that could not run must not read as a clean result. WARN exits
        # 0, so a transient OSV outage would otherwise turn this gate green
        # while checking nothing.
        return [Finding("ERROR", "deps", "-", f"OSV query failed: {exc}")]

    for (name, version), result in zip(installed, results, strict=False):
        vulns = result.get("vulns", [])
        if vulns:
            ids = ", ".join(v.get("id", "?") for v in vulns[:5])
            findings.append(
                Finding("ERROR", "deps", f"{name}=={version}", f"known vulnerabilities: {ids}")
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deps", action="store_true")
    parser.add_argument("--secrets", action="store_true")
    args = parser.parse_args()

    if not (args.deps or args.secrets):
        parser.error("select at least one of --deps / --secrets")

    findings: list[Finding] = []
    if args.secrets:
        findings.extend(scan_secrets())
    if args.deps:
        findings.extend(scan_dependencies())

    for finding in findings:
        print(f"[{finding.severity}] {finding.category}: {finding.location} -> {finding.detail}")

    errors = [f for f in findings if f.severity == "ERROR"]
    print(f"\n{len(errors)} error(s), {len(findings) - len(errors)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
