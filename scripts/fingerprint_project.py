#!/usr/bin/env python3
"""
fingerprint_project.py - dependency-free structural fingerprint for code-analyze's
similarity/history corpus.

Walks a repository and produces a JSON fingerprint used to compare this project
against others previously analyzed:
  - per-language file counts (reuses the same table as count_loc.py, so the two
    scripts agree on what "Python" or "C++" means)
  - best-effort dependency manifest contents (package names only)
  - per-file: a normalized-content hash (catches exact/near-exact structural
    duplicates cheaply) and a bottom-k MinHash sketch over token shingles
    (estimates Jaccard similarity even when code has been edited/reordered)
  - one project-level bottom-k MinHash sketch (union of all file shingles), for
    a fast whole-project similarity estimate

Normalization strips comments/blank lines (per-language rules, borrowed from
count_loc.py) and replaces string/numeric literals with placeholders, so the
fingerprint is robust to renamed constants and reformatting but still sensitive
to actual structure - it approximates "Type-2" code-clone detection. Identifiers
are deliberately NOT normalized, so a clone with every variable renamed will
score lower on the file-pair check; the shingle overlap still tends to survive
partially. That is a known limitation, not a bug - see SKILL.md's "Corpus &
similarity history" section.

This script never stores or emits source code itself - only one-way hashes,
sketches, and metadata (relative paths, languages, dependency names). Pair with
compare_fingerprint.py to score a fingerprint against a corpus directory.

Usage:
    python fingerprint_project.py <repo-path> [--out FILE] [--all]
                                   [--shingle-size N] [--file-sketch-k N]
                                   [--project-sketch-k N]

    --out FILE          write JSON here instead of stdout.
    --all               include normally-skipped dirs (node_modules, .git, ...).
    --shingle-size N    token k-gram size for the code-similarity sketch (default 5).
    --file-sketch-k N   bottom-k sketch size per file (default 64).
    --project-sketch-k N  bottom-k sketch size for the whole project (default 256).
"""

import argparse
import datetime
import hashlib
import heapq
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from count_loc import LANGS, SKIP_DIRS  # noqa: E402  (reuse the same tables)

# "Code" extensions for shingling/similarity - excludes markup/data/docs, which
# would add noise (two unrelated projects sharing a stock package.json or a
# Bootstrap-derived CSS file shouldn't register as "similar").
_NOT_CODE_LANGS = {
    "JSON", "XML", "HTML", "CSS", "SCSS", "YAML", "TOML", "INI",
    "Markdown", "reStructuredText", "Text",
}
CODE_EXTS = {ext for ext, (lang, _, _) in LANGS.items() if lang not in _NOT_CODE_LANGS}

MAX_BYTES = 2_000_000
STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`')
NUMBER_RE = re.compile(r'\b0[xX][0-9a-fA-F]+\b|\b\d+\.\d+\b|\b\d+\b')
TOKEN_RE = re.compile(r'\w+|[^\w\s]')


class BottomK:
    """Keeps the k smallest *distinct* hash values seen (a KMV / bottom-k sketch),
    which lets two sketches estimate the Jaccard similarity of their full,
    unseen-by-each-other input sets without storing those sets."""

    __slots__ = ("k", "heap", "seen")

    def __init__(self, k):
        self.k = k
        self.heap = []       # max-heap of the kept values, via negation
        self.seen = set()

    def add(self, h):
        if h in self.seen:
            return
        neg = -h
        if len(self.heap) < self.k:
            heapq.heappush(self.heap, neg)
            self.seen.add(h)
        elif neg > self.heap[0]:
            old = -heapq.heapreplace(self.heap, neg)
            self.seen.discard(old)
            self.seen.add(h)

    def sketch(self):
        return sorted(-x for x in self.heap)


def strip_comments(text, line_tokens, block):
    """Line-oriented comment/blank stripping - mirrors count_loc.count_lines
    closely enough that the two scripts classify code the same way."""
    b_open, b_close = (block if block else (None, None))
    in_block = False
    out_lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if in_block:
            if b_close and b_close in s:
                in_block = False
            continue
        if b_open and s.startswith(b_open):
            if not (b_close and b_close in s[len(b_open):]):
                in_block = True
            continue
        if any(tok and s.lower().startswith(tok) for tok in line_tokens):
            continue
        out_lines.append(s)
    return "\n".join(out_lines)


def normalize(text):
    """Placeholder-out string/numeric literals so constant changes don't mask
    structural similarity (a lightweight Type-2 clone normalization)."""
    text = STRING_RE.sub("STR", text)
    text = NUMBER_RE.sub("NUM", text)
    return text


def shingles(tokens, size):
    if len(tokens) < size:
        if tokens:
            yield tuple(tokens)
        return
    for i in range(len(tokens) - size + 1):
        yield tuple(tokens[i:i + size])


def hash_shingle(sh):
    data = "".join(sh).encode("utf-8", "replace")
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "big")


def fingerprint_file(path, line_tokens, block, shingle_size, file_k, project_sketch):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        return None
    stripped = strip_comments(raw, line_tokens, block)
    if not stripped.strip():
        return None
    norm = normalize(stripped)
    norm_hash = hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()
    tokens = TOKEN_RE.findall(norm)
    file_sketch = BottomK(file_k)
    n_shingles = 0
    for sh in shingles(tokens, shingle_size):
        h = hash_shingle(sh)
        file_sketch.add(h)
        project_sketch.add(h)
        n_shingles += 1
    return {"norm_hash": norm_hash, "shingles": n_shingles, "sketch": file_sketch.sketch()}


def _names_from_json_deps(data):
    names = set()
    for key in ("dependencies", "devDependencies"):
        names.update(data.get(key, {}) or {})
    return sorted(names)


def collect_dependencies(root):
    """Best-effort dependency-name extraction from common manifest formats.
    Package *names* only - never lockfile hashes or full manifest contents."""
    deps = {}

    pkg = os.path.join(root, "package.json")
    if os.path.isfile(pkg):
        try:
            with open(pkg, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            names = _names_from_json_deps(data)
            if names:
                deps["package.json"] = names
        except (OSError, ValueError):
            pass

    req = os.path.join(root, "requirements.txt")
    if os.path.isfile(req):
        names = []
        try:
            with open(req, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    name = re.split(r"[=<>!~\[; ]", line, 1)[0].strip()
                    if name:
                        names.append(name)
        except OSError:
            pass
        if names:
            deps["requirements.txt"] = sorted(set(names))

    gomod = os.path.join(root, "go.mod")
    if os.path.isfile(gomod):
        try:
            with open(gomod, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            names = re.findall(r'^\s*([a-zA-Z0-9_.\-/]+)\s+v[\d.]+', text, re.M)
            if names:
                deps["go.mod"] = sorted(set(names))
        except OSError:
            pass

    cargo = os.path.join(root, "Cargo.toml")
    if os.path.isfile(cargo):
        try:
            with open(cargo, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            m = re.search(r"\[dependencies\](.*?)(\n\[|\Z)", text, re.S)
            if m:
                names = re.findall(r'^\s*([A-Za-z0-9_\-]+)\s*=', m.group(1), re.M)
                if names:
                    deps["Cargo.toml"] = sorted(set(names))
        except OSError:
            pass

    return deps


def main():
    ap = argparse.ArgumentParser(description="Structural fingerprint for the code-analyze similarity corpus.")
    ap.add_argument("repo")
    ap.add_argument("--out", help="Write JSON here instead of stdout.")
    ap.add_argument("--all", action="store_true", help="Include normally-skipped dirs.")
    ap.add_argument("--shingle-size", type=int, default=5)
    ap.add_argument("--file-sketch-k", type=int, default=64)
    ap.add_argument("--project-sketch-k", type=int, default=256)
    args = ap.parse_args()

    root = os.path.abspath(args.repo)
    if not os.path.isdir(root):
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    project_sketch = BottomK(args.project_sketch_k)
    files_out = []
    lang_counts = {}

    for dirpath, dirnames, filenames in os.walk(root):
        if not args.all:
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in CODE_EXTS:
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > MAX_BYTES:
                    continue
            except OSError:
                continue
            lang, line_tokens, block = LANGS[ext]
            fp = fingerprint_file(full, line_tokens, block, args.shingle_size,
                                   args.file_sketch_k, project_sketch)
            if fp is None:
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            fp["path"] = rel
            fp["lang"] = lang
            files_out.append(fp)
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

    out = {
        "schema_version": 1,
        "fingerprinted_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": root,
        "shingle_size": args.shingle_size,
        "file_sketch_k": args.file_sketch_k,
        "project_sketch_k": args.project_sketch_k,
        "project_sketch": project_sketch.sketch(),
        "language_summary": lang_counts,
        "file_count": len(files_out),
        "dependency_manifests": collect_dependencies(root),
        "files": files_out,
        "analysis": None,  # filled in by the skill after the report is written
    }

    text = json.dumps(out, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote fingerprint ({len(files_out)} files, "
              f"{len(out['project_sketch'])}-value project sketch) to {args.out}",
              file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
