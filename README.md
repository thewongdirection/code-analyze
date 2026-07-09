# code-analyze

A [Claude](https://claude.com/claude-code) skill for **whole-codebase analysis and security review**.

Point it at a GitHub repository (URL) or a local checkout and it acts as a senior
software engineer, code reviewer, and cybersecurity specialist: it reads the code,
explains what the project is and what it can actually do, and produces both a
structured Markdown report and a self-contained HTML dashboard.

## What it produces

- **Overview & architecture** — what the project is, its stack, entry points, and key modules.
- **Core features & capabilities** — traced from the source, reconciled against the README.
- **Networking & cryptography** — outbound/inbound endpoints, protocols, TLS posture, crypto primitives, and **network signatures / IOCs** (or host-based signatures when there's no network).
- **Potential vulnerabilities** — hardcoded secrets, injection, unsafe deserialization, weak/misused crypto, auth gaps, supply-chain risk — each rated by severity with `file:line` and why it matters.
- **Replication & feature-match assessment** — how hard the app would be to rebuild, what's commodity vs. differentiated, and whether there's any real moat.
- **Two deliverables** — an authoritative `CODE-ANALYSIS.md` and a glanceable, theme-aware dashboard, delivered as **HTML, PDF, or both** (the PDF is rendered from the same HTML, so they never drift).

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
| `scripts/count_loc.py` | Dependency-free per-language line-count metrics for the report/dashboard. |
| `scripts/html_to_pdf.py` | Renders the HTML dashboard to PDF via headless Chrome/Edge/Chromium (falls back to weasyprint). |
| `assets/dashboard-template.html` | Self-contained, theme-aware HTML dashboard skeleton (with print/PDF styles). |

## Installation

Copy this folder into your Claude skills directory (e.g. `~/.claude/skills/code-analyze`),
then invoke it by asking Claude to analyze, review, or audit a repository.

## Scope & honesty

This is **read-only static analysis** — it does not run untrusted code from the
target repo, and it is not a substitute for a full penetration test or a dedicated
SAST tool. It flags what a sharp reviewer would catch on a careful read, and is
clear about the limits of that.
