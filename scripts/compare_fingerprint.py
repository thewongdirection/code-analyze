#!/usr/bin/env python3
"""
compare_fingerprint.py - score a project fingerprint (from fingerprint_project.py)
against a local corpus of previously analyzed projects, for code-analyze's
similarity/history feature.

Reports two independent signals per prior project, kept separate rather than
blended into one opaque number, plus a combined score for ranking:
  - Code similarity - a bottom-k MinHash Jaccard estimate between project-level
    shingle sketches, plus a drill-down into specific near-duplicate/high-overlap
    file pairs. This is what catches a copy-pasted or lightly-modified module or
    algorithm even if surrounding code and file names differ.
  - Metadata/IOC overlap - shared dependency names, and (once the fingerprint's
    "analysis" block has been filled in after the report is written) shared
    network IOCs and crypto primitives. Exact-match, not fuzzy - hostnames and
    mutex names either match or they don't.

Usage:
    python compare_fingerprint.py <fingerprint.json> <corpus-dir>
                                   [--top N] [--min-score F] [--json]
                                   [--max-file-pairs N]

    --top N            max prior projects to report (default 10).
    --min-score F       drop matches below this combined score, 0-1 (default 0.15).
    --max-file-pairs N  cap near-duplicate file pairs listed per match (default 20).
    --json              machine-readable output instead of the text report.
"""

import argparse
import json
import os
import sys


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def estimate_jaccard(sketch_a, sketch_b):
    """KMV / bottom-k Jaccard estimator. Valid even when the two sketches were
    built with different k - a bottom-k sketch's own prefix of length j<k is
    itself the true bottom-j, so truncating both to the smaller k is sound."""
    k = min(len(sketch_a), len(sketch_b))
    if k == 0:
        return 0.0
    set_a, set_b = set(sketch_a[:k]), set(sketch_b[:k])
    merged = sorted(set_a | set_b)[:k]
    if not merged:
        return 0.0
    both = sum(1 for h in merged if h in set_a and h in set_b)
    return both / len(merged)


def file_similarities(new_files, prior_files, max_pairs):
    """Near-duplicate / high-overlap file pairs. Same-language only (cuts noise
    and comparison count); exact normalized-hash match short-circuits to 100%."""
    by_lang = {}
    for pf in prior_files:
        by_lang.setdefault(pf.get("lang"), []).append(pf)

    results = []
    for nf in new_files:
        for pf in by_lang.get(nf.get("lang"), []):
            if nf.get("norm_hash") and nf["norm_hash"] == pf.get("norm_hash"):
                results.append((1.0, nf["path"], pf["path"], "exact structural match"))
                continue
            score = estimate_jaccard(nf.get("sketch", []), pf.get("sketch", []))
            if score >= 0.5:
                results.append((score, nf["path"], pf["path"], "shingle overlap"))
    results.sort(key=lambda r: r[0], reverse=True)
    return results[:max_pairs]


def dep_names(dep_manifests):
    names = set()
    for lst in (dep_manifests or {}).values():
        names.update(lst)
    return names


def meta_set(fp):
    """Everything used for the metadata/IOC overlap score: dependency names
    plus (if present) network IOCs and crypto primitives from the analysis
    block. Never includes actual secret values - those aren't stored here."""
    names = set(dep_names(fp.get("dependency_manifests")))
    analysis = fp.get("analysis") or {}
    names.update(analysis.get("network_iocs", []) or [])
    names.update(analysis.get("crypto_primitives", []) or [])
    return names


def score_against(new_fp, prior_fp, max_file_pairs):
    code_sim = estimate_jaccard(new_fp.get("project_sketch", []), prior_fp.get("project_sketch", []))
    pairs = file_similarities(new_fp.get("files", []), prior_fp.get("files", []), max_file_pairs)

    shared_deps = sorted(dep_names(new_fp.get("dependency_manifests")) & dep_names(prior_fp.get("dependency_manifests")))
    new_analysis = new_fp.get("analysis") or {}
    prior_analysis = prior_fp.get("analysis") or {}
    shared_iocs = sorted(set(new_analysis.get("network_iocs", []) or []) & set(prior_analysis.get("network_iocs", []) or []))
    shared_crypto = sorted(set(new_analysis.get("crypto_primitives", []) or []) & set(prior_analysis.get("crypto_primitives", []) or []))

    new_meta, prior_meta = meta_set(new_fp), meta_set(prior_fp)
    union = new_meta | prior_meta
    ioc_score = (len(new_meta & prior_meta) / len(union)) if union else 0.0

    combined = 0.6 * code_sim + 0.4 * ioc_score

    return {
        "combined": combined,
        "code_similarity": code_sim,
        "ioc_metadata_overlap": ioc_score,
        "file_pairs": pairs,
        "shared_dependencies": shared_deps,
        "shared_network_iocs": shared_iocs,
        "shared_crypto_primitives": shared_crypto,
    }


def main():
    ap = argparse.ArgumentParser(description="Compare a fingerprint against the local similarity corpus.")
    ap.add_argument("fingerprint", help="Path to this project's fingerprint JSON.")
    ap.add_argument("corpus_dir", help="Directory of prior fingerprint JSON files.")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--min-score", type=float, default=0.15)
    ap.add_argument("--max-file-pairs", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    new_fp = load(args.fingerprint)

    if not os.path.isdir(args.corpus_dir):
        if args.json:
            print(json.dumps({"corpus_projects": 0, "matches": []}))
        else:
            print(f"No corpus directory at {args.corpus_dir} yet - nothing to compare against "
                  f"(this will be its first entry).")
        return 0

    corpus_files = sorted(f for f in os.listdir(args.corpus_dir) if f.endswith(".json"))
    new_root = os.path.abspath(new_fp.get("root", ""))
    new_ts = new_fp.get("fingerprinted_at")

    matches = []
    for fn in corpus_files:
        full = os.path.join(args.corpus_dir, fn)
        try:
            prior_fp = load(full)
        except (OSError, ValueError):
            continue
        if os.path.abspath(prior_fp.get("root", "")) == new_root and prior_fp.get("fingerprinted_at") == new_ts:
            continue  # this is the fingerprint being compared, already present in the corpus
        result = score_against(new_fp, prior_fp, args.max_file_pairs)
        if result["combined"] < args.min_score:
            continue
        analysis = prior_fp.get("analysis") or {}
        result["corpus_file"] = fn
        result["project_name"] = analysis.get("project_name", fn)
        result["source"] = analysis.get("source", prior_fp.get("root", "unknown"))
        result["analyzed_at"] = analysis.get("analyzed_at", prior_fp.get("fingerprinted_at", "unknown"))
        matches.append(result)

    matches.sort(key=lambda r: r["combined"], reverse=True)
    matches = matches[:args.top]

    if args.json:
        print(json.dumps({"corpus_projects": len(corpus_files), "matches": matches}, indent=2))
        return 0

    print(f"\nCompared against {len(corpus_files)} prior project(s) in the corpus.\n")
    if not matches:
        print(f"No meaningfully similar prior analyses found (above {args.min_score:.0%} combined score).")
        return 0

    for m in matches:
        print(f"{m['project_name']}  (source: {m['source']}, analyzed: {m['analyzed_at']})")
        print(f"  Combined similarity: {m['combined']:.0%}   "
              f"[code: {m['code_similarity']:.0%}  |  metadata/IOC: {m['ioc_metadata_overlap']:.0%}]")
        if m["file_pairs"]:
            print(f"  Near-duplicate/high-overlap files ({len(m['file_pairs'])}):")
            for score, np_, pp_, kind in m["file_pairs"]:
                print(f"    {score:.0%}  {np_}  <->  {pp_}  ({kind})")
        if m["shared_dependencies"]:
            print(f"  Shared dependencies: {', '.join(m['shared_dependencies'])}")
        if m["shared_network_iocs"]:
            print(f"  Shared network IOCs: {', '.join(m['shared_network_iocs'])}")
        if m["shared_crypto_primitives"]:
            print(f"  Shared crypto primitives: {', '.join(m['shared_crypto_primitives'])}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
