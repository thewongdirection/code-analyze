#!/usr/bin/env python3
"""
count_loc.py — dependency-free code metrics for code-analyze.

Walks a repository, classifies files by language (extension), and counts lines
(total / code / blank / comment). Produces the numbers behind the dashboard's
metric tiles and the per-language breakdown, so those are measured, not guessed.

Usage:
    python count_loc.py <repo-path> [--json] [--all]

    --json  emit machine-readable JSON instead of the text table.
    --all   include normally-skipped dirs (node_modules, vendor, build, .git…).

Notes / honesty:
  - Comment counting is heuristic (line-oriented, common syntaxes). It is good
    enough for a dashboard tile, not a billing-grade SLOC tool. "Code" = total
    minus blank minus comment lines.
  - Binary and unknown-extension files are counted toward file totals under
    "(other)" but contribute no line counts.
"""

import argparse
import json
import os
import sys

# Directories not worth counting (mirrors scan_secrets.py so the two agree).
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "bower_components",
    "dist", "build", "out", "target", "bin", "obj", ".next", ".nuxt",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".gradle", ".idea", ".vs", "coverage", ".terraform",
}

# extension -> (language, line-comment tokens, (block_open, block_close) or None)
LANGS = {
    ".c":    ("C", ["//"], ("/*", "*/")),
    ".h":    ("C/C++ Header", ["//"], ("/*", "*/")),
    ".hpp":  ("C++ Header", ["//"], ("/*", "*/")),
    ".cc":   ("C++", ["//"], ("/*", "*/")),
    ".cpp":  ("C++", ["//"], ("/*", "*/")),
    ".cxx":  ("C++", ["//"], ("/*", "*/")),
    ".cs":   ("C#", ["//"], ("/*", "*/")),
    ".java": ("Java", ["//"], ("/*", "*/")),
    ".js":   ("JavaScript", ["//"], ("/*", "*/")),
    ".jsx":  ("JavaScript", ["//"], ("/*", "*/")),
    ".mjs":  ("JavaScript", ["//"], ("/*", "*/")),
    ".ts":   ("TypeScript", ["//"], ("/*", "*/")),
    ".tsx":  ("TypeScript", ["//"], ("/*", "*/")),
    ".go":   ("Go", ["//"], ("/*", "*/")),
    ".rs":   ("Rust", ["//"], ("/*", "*/")),
    ".swift":("Swift", ["//"], ("/*", "*/")),
    ".kt":   ("Kotlin", ["//"], ("/*", "*/")),
    ".php":  ("PHP", ["//", "#"], ("/*", "*/")),
    ".py":   ("Python", ["#"], None),
    ".rb":   ("Ruby", ["#"], None),
    ".pl":   ("Perl", ["#"], None),
    ".sh":   ("Shell", ["#"], None),
    ".bash": ("Shell", ["#"], None),
    ".ps1":  ("PowerShell", ["#"], ("<#", "#>")),
    ".psm1": ("PowerShell", ["#"], ("<#", "#>")),
    ".bat":  ("Batch", ["rem ", "::"], None),
    ".cmd":  ("Batch", ["rem ", "::"], None),
    ".sql":  ("SQL", ["--"], ("/*", "*/")),
    ".r":    ("R", ["#"], None),
    ".lua":  ("Lua", ["--"], ("--[[", "]]")),
    ".scala":("Scala", ["//"], ("/*", "*/")),
    ".m":    ("Objective-C", ["//"], ("/*", "*/")),
    ".yaml": ("YAML", ["#"], None),
    ".yml":  ("YAML", ["#"], None),
    ".toml": ("TOML", ["#"], None),
    ".ini":  ("INI", [";", "#"], None),
    ".json": ("JSON", [], None),
    ".xml":  ("XML", [], ("<!--", "-->")),
    ".html": ("HTML", [], ("<!--", "-->")),
    ".htm":  ("HTML", [], ("<!--", "-->")),
    ".css":  ("CSS", [], ("/*", "*/")),
    ".scss": ("SCSS", ["//"], ("/*", "*/")),
    ".md":   ("Markdown", [], None),
    ".rst":  ("reStructuredText", [], None),
    ".txt":  ("Text", [], None),
}


def count_lines(path, line_tokens, block):
    """Return (total, blank, comment). Best-effort, line-oriented."""
    total = blank = comment = 0
    in_block = False
    b_open, b_close = (block if block else (None, None))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                total += 1
                s = raw.strip()
                if not s:
                    blank += 1
                    continue
                if in_block:
                    comment += 1
                    if b_close and b_close in s:
                        in_block = False
                    continue
                if b_open and s.startswith(b_open):
                    comment += 1
                    # single-line block comment stays closed
                    if not (b_close and b_close in s[len(b_open):]):
                        in_block = True
                    continue
                if any(tok and s.lower().startswith(tok) for tok in line_tokens):
                    comment += 1
    except OSError:
        return (0, 0, 0)
    return (total, blank, comment)


def main():
    ap = argparse.ArgumentParser(description="Dependency-free code metrics.")
    ap.add_argument("repo")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.repo)
    if not os.path.isdir(root):
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    # lang -> [files, total, code, blank, comment]
    stats = {}
    other_files = 0
    grand_files = 0

    for dirpath, dirnames, filenames in os.walk(root):
        if not args.all:
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            grand_files += 1
            ext = os.path.splitext(fn)[1].lower()
            spec = LANGS.get(ext)
            if not spec:
                other_files += 1
                continue
            lang, line_tokens, block = spec
            total, blank, comment = count_lines(
                os.path.join(dirpath, fn), line_tokens, block)
            code = total - blank - comment
            row = stats.setdefault(lang, [0, 0, 0, 0, 0])
            row[0] += 1
            row[1] += total
            row[2] += code
            row[3] += blank
            row[4] += comment

    langs_sorted = sorted(stats.items(), key=lambda kv: kv[1][2], reverse=True)
    tot_code = sum(r[2] for _, r in langs_sorted)
    tot_total = sum(r[1] for _, r in langs_sorted)
    counted_files = sum(r[0] for _, r in langs_sorted)

    if args.json:
        out = {
            "root": root,
            "total_files": grand_files,
            "counted_files": counted_files,
            "other_files": other_files,
            "language_count": len(stats),
            "total_lines": tot_total,
            "total_code_lines": tot_code,
            "languages": [
                {"language": l, "files": r[0], "total": r[1],
                 "code": r[2], "blank": r[3], "comment": r[4]}
                for l, r in langs_sorted
            ],
        }
        print(json.dumps(out, indent=2))
        return 0

    print(f"\nCode metrics for {root}\n")
    print(f"{'Language':<20}{'Files':>7}{'Code':>9}{'Comment':>9}{'Blank':>8}{'Total':>9}")
    print("-" * 62)
    for lang, r in langs_sorted:
        print(f"{lang:<20}{r[0]:>7}{r[2]:>9}{r[4]:>9}{r[3]:>8}{r[1]:>9}")
    print("-" * 62)
    print(f"{'TOTAL':<20}{counted_files:>7}{tot_code:>9}"
          f"{sum(r[4] for _,r in langs_sorted):>9}"
          f"{sum(r[3] for _,r in langs_sorted):>8}{tot_total:>9}")
    print(f"\nLanguages: {len(stats)} | Counted files: {counted_files} | "
          f"Other/binary files: {other_files} | All files: {grand_files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
