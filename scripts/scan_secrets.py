#!/usr/bin/env python3
"""
scan_secrets.py — high-signal secret / credential sweep for code-analyze.

Walks a repository, matches known secret formats plus generic credential
assignments, and prints `path:line: <type>: <redacted match>`.

This is intentionally a NET, not a verdict. It over-flags (test fixtures,
example configs, placeholders will match). Triage the output by reading the
actual code. It will also miss secrets built from concatenation or unusual
custom formats, so it complements manual review rather than replacing it.

Usage:
    python scan_secrets.py <repo-path> [--all]

    --all   also scan files/dirs normally skipped (vendored deps, minified,
            larger files). Slower and noisier.
"""

import argparse
import os
import re
import sys

# Directories that are almost never worth scanning: VCS internals, vendored
# dependencies, build output, virtualenvs. Skipping these cuts noise massively.
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "bower_components",
    "dist", "build", "out", "target", "bin", "obj", ".next", ".nuxt",
    "__pycache__", ".venv", "venv", "env", ".env.d", ".tox", ".mypy_cache",
    ".pytest_cache", ".gradle", ".idea", ".vs", "coverage", ".terraform",
}

# Binary / non-source extensions: no point regex-scanning these.
SKIP_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".pdf", ".zip", ".gz", ".tar", ".7z", ".rar", ".jar", ".war", ".class",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".lib", ".pdb", ".bin",
    ".mp3", ".mp4", ".wav", ".mov", ".avi", ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".pyo", ".lock", ".map", ".min.js", ".min.css",
}

MAX_BYTES = 2_000_000   # skip files larger than this unless --all
MAX_LINE = 500          # ignore absurdly long lines (usually minified/base64 blobs) unless --all

# (name, compiled regex). Ordered from most specific/high-confidence downward.
PATTERNS = [
    ("AWS Access Key ID", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA)[0-9A-Z]{16}\b")),
    ("AWS Secret Access Key", re.compile(r"(?i)aws.{0,20}?(?:secret|sk).{0,20}?['\"][0-9a-zA-Z/+]{40}['\"]")),
    ("Private Key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("Certificate (PEM)", re.compile(r"-----BEGIN CERTIFICATE-----")),
    ("Certificate request (CSR)", re.compile(r"-----BEGIN (?:NEW )?CERTIFICATE REQUEST-----")),
    ("Public Key (PEM)", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PUBLIC KEY-----")),
    ("PGP block", re.compile(r"-----BEGIN PGP (?:PUBLIC KEY BLOCK|PRIVATE KEY BLOCK|SIGNATURE|MESSAGE)-----")),
    ("SSH public key", re.compile(r"\b(?:ssh-(?:rsa|dss|ed25519)|ecdsa-sha2-nistp\d+)\s+AAAA[0-9A-Za-z+/]{20,}")),
    ("GitHub Token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[0-9A-Za-z_]{20,}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("Slack Webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+")),
    ("Stripe Live Key", re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}\b")),
    ("Stripe Test Key", re.compile(r"\b(?:sk|rk|pk)_test_[0-9A-Za-z]{20,}\b")),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Google OAuth ID", re.compile(r"\b[0-9]+-[0-9A-Za-z_]{32}\.apps\.googleusercontent\.com\b")),
    ("Twilio Key", re.compile(r"\bSK[0-9a-fA-F]{32}\b")),
    ("SendGrid Key", re.compile(r"\bSG\.[0-9A-Za-z_\-]{22}\.[0-9A-Za-z_\-]{43}\b")),
    ("NPM Token", re.compile(r"\bnpm_[0-9A-Za-z]{36}\b")),
    ("Heroku/UUID-style API Key", re.compile(r"(?i)heroku.{0,20}?['\"][0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}['\"]")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("Basic Auth in URL", re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s:@]+:[^/\s:@]+@[^\s/]+")),
    ("DB Connection String w/ password", re.compile(r"(?i)(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|amqp|mssql|jdbc:[a-z]+)://[^\s:@/]+:[^\s:@/]+@")),
    # Generic assignments: key-ish name = quoted value. High recall, lower precision.
    ("Generic secret assignment", re.compile(
        r"(?i)(?:password|passwd|pwd|secret|api[_-]?key|apikey|access[_-]?token|auth[_-]?token|"
        r"client[_-]?secret|private[_-]?key|encryption[_-]?key|session[_-]?key)"
        r"\s*[:=]\s*['\"][^'\"\n]{6,}['\"]")),
]

# Values that make a "Generic secret assignment" almost certainly a placeholder.
PLACEHOLDER_HINT = re.compile(
    r"(?i)(your[_-]?|example|placeholder|changeme|change_me|xxxx|<[^>]+>|\$\{|%\(|"
    r"\{\{|dummy|sample|todo|redacted|insert|none|null|true|false|test123|password123)")


def is_probably_text(path):
    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)
        if b"\x00" in chunk:
            return False
        return True
    except OSError:
        return False


def scan_file(path, scan_all):
    findings = []
    try:
        if not scan_all and os.path.getsize(path) > MAX_BYTES:
            return findings
    except OSError:
        return findings
    if not is_probably_text(path):
        return findings
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                if not scan_all and len(line) > MAX_LINE:
                    continue
                for name, rx in PATTERNS:
                    m = rx.search(line)
                    if not m:
                        continue
                    span = m.group(0)
                    tag = name
                    if name == "Generic secret assignment" and PLACEHOLDER_HINT.search(span):
                        tag = "Generic secret assignment (likely placeholder)"
                    redacted = span if len(span) <= 60 else span[:40] + "…" + span[-8:]
                    findings.append((lineno, tag, redacted.strip()))
    except OSError:
        pass
    return findings


def main():
    ap = argparse.ArgumentParser(description="High-signal secret/credential sweep.")
    ap.add_argument("repo", help="Path to the repository root to scan.")
    ap.add_argument("--all", action="store_true",
                    help="Also scan normally-skipped dirs, large files, and long lines.")
    args = ap.parse_args()

    root = os.path.abspath(args.repo)
    if not os.path.isdir(root):
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    total = 0
    files_with_hits = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if not args.all:
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if not args.all and ext in SKIP_EXTS:
                continue
            full = os.path.join(dirpath, fn)
            hits = scan_file(full, args.all)
            if hits:
                files_with_hits += 1
                rel = os.path.relpath(full, root)
                for lineno, tag, redacted in hits:
                    total += 1
                    print(f"{rel}:{lineno}: {tag}: {redacted}")

    print(f"\n--- {total} potential finding(s) across {files_with_hits} file(s). "
          f"Triage each by reading the source; over-flagging is expected. ---",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
