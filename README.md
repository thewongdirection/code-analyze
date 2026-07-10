# code-analyze

A [Claude](https://claude.com/claude-code) skill for **whole-codebase analysis and security review**.

Point it at a GitHub repository (URL) or a local checkout and it acts as a senior
software engineer, reverse engineer, code reviewer, and cybersecurity specialist —
with cross-platform depth across Windows, Linux, Android, and iOS: it reads the
code, explains what the project is and what it can actually do, and produces a
single professional evaluation report — one self-contained HTML plus a matching PDF.

## What it produces

- **Overview & architecture** — what the project is, its stack, entry points, and key modules.
- **Core features & capabilities** — traced from the executing code, not from the README or the code's own comments; those are used only to corroborate or to flag a mismatch.
- **Networking & cryptography** — outbound/inbound endpoints, protocols, TLS posture, crypto primitives, and **network signatures / IOCs** (or host-based signatures when there's no network).
- **Potential vulnerabilities** — hardcoded secrets, injection, unsafe deserialization, weak/misused crypto, auth gaps, supply-chain risk — each rated by severity with `file:line` and why it matters.
- **Single deliverable** — one self-contained **HTML evaluation report** and a **matching PDF** rendered from it (so they never drift). Everything collates into that one document: executive summary, metrics, architecture, capabilities (framed by the API set that implements them), system-interaction surface, networking/crypto, findings, a **methodology & reproduction appendix**, and an **embedded interactive call tree** — an IDA-Pro-style horizontal hierarchy (entry point on the left, callees expanding right, collapsible subtrees).

## Approach

The skill reads **every file, every line** (working from a local copy for large
repos), rather than skimming — the interesting findings tend to hide in files that
look like boilerplate. It states its coverage honestly and lists any binary files
it could not read.

## Contents

| Path | Purpose |
|------|---------|
| `SKILL.md` | The skill definition and methodology. |
| `scripts/scan_secrets.py` | Dependency-free regex sweep for secrets/credentials (a triage net, not a verdict). |
| `scripts/count_loc.py` | Dependency-free per-language line-count metrics for the report. |
| `scripts/html_to_pdf.py` | Renders the HTML report to a matching PDF via headless Chrome/Edge/Chromium (falls back to weasyprint). |
| `assets/report-template.html` | **The consolidated evaluation-report scaffold** — cover, all sections, embedded call tree, and reproduction appendix, in one self-contained file. |
| `assets/dashboard-template.html` | Standalone dashboard skeleton (a component; the report template supersedes it as the deliverable). |
| `assets/callgraph-template.html` | Standalone IDA-style call-tree skeleton (a component; also embedded in the report template). |

## Installation

Copy this folder into your Claude skills directory (e.g. `~/.claude/skills/code-analyze`),
then invoke it by asking Claude to analyze, review, or audit a repository.

## Scope & honesty

This is **read-only static analysis** — it does not run untrusted code from the
target repo, and it is not a substitute for a full penetration test or a dedicated
SAST tool. It flags what a sharp reviewer would catch on a careful read, and is
clear about the limits of that.
