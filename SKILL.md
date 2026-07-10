---
name: code-analyze
description: Given a GitHub repository (a URL or a local checkout), perform a thorough, whole-codebase analysis acting as a senior software engineer, code reviewer, and cybersecurity specialist. Study the files, explain what the project is and what it can actually do, highlight the key artifacts (entry points, core modules, notable capabilities), identify the key networking and cryptographic functionality (including network signatures / detection indicators), and produce a dedicated security section flagging potential vulnerabilities, hardcoded passwords or API keys in plaintext, and embedded credentials. It also names the core features, outlines the operating footprint (deployed files, required libraries, probable process/host identity, and any certificates/keys/signatures), and assesses how hard the app would be to replicate or feature-match. Deliver everything as a single professional evaluation report — one self-contained HTML plus a matching PDF — collating the findings, an embedded interactive call tree, and a methodology/reproduction appendix. Use this whenever the user points at a repo — a GitHub link, a cloned folder, "analyze this codebase", "review this repo", "what does this project do", "audit this code", "check this for secrets/vulnerabilities/crypto/networking", or hands over a project and asks what it is or whether it's safe — even if they don't use the word "analyze". Prefer this over an ad-hoc skim whenever the goal is understanding or vetting an entire project rather than editing a specific file.
---

# Code Analyze

## What this does

Given a repository, produce a single, well-structured report that answers three questions a skilled engineer would ask on first contact:

1. **What is this?** — the project's purpose, stack, and shape.
2. **What can it actually do?** — its real capabilities, traced from the code, not just the README's claims.
3. **Is it safe?** — a security pass that surfaces embedded credentials, hardcoded secrets, and code patterns that are plausibly exploitable.

The value is in reading the *actual code* and reconciling it with what the project claims about itself. READMEs lie, go stale, or describe aspirations; the code is ground truth. Your report should reflect what you found in the source, and call out where the code and the documentation disagree.

## Getting the code

Always analyze from a **local working copy on fast local storage**, so that reading every file (see below) is quick and repeatable. Create a disposable folder in the scratchpad and work there — never modify the user's original tree.

- **GitHub URL** → clone it into the scratchpad. A shallow clone is enough and much faster:
  `git clone --depth 1 <url> <scratchpad>/code-analyze/<repo-name>`
  If the clone fails (private repo, auth), tell the user and ask how they'd like to proceed rather than guessing.
- **Local path** → for a small project you may read it in place (read-only). For anything large, or anything on a slow/network drive, **copy it into a scratchpad folder first** and read from that copy, so the exhaustive full-read pass is fast and you never risk touching the original. Exclude only the un-analyzable bulk (`.git/`, `node_modules/`, build output, virtualenvs) from the copy — everything else comes along.

## The analysis pass

**Read every file, and every line of it.** This is a thoroughness-first analysis: the goal is complete coverage, not a fast skim. Build a map first so you read in a sensible order and know how the pieces connect, but then actually read the whole tree — do not sample, do not "skim the rest," do not assume a file is boilerplate from its name. Things that look like glue (config, `__init__.py`, small utils, test files, prompt/`.txt` assets, CI YAML) are exactly where secrets, hidden endpoints, disabled TLS, and surprising behaviour hide. Working from a local copy (above) makes this affordable.

The only things you may leave unread are files that genuinely cannot be read as source: binary blobs (compiled artifacts, images, `.whl`/`.jar`, model weights like `.npy`, media). List those explicitly and note that they were not disassembled, rather than silently skipping them. Enormous generated/vendored trees (a checked-in `node_modules`, minified bundles, lockfiles) should be excluded from the copy up front; if any remain, read enough to confirm what they are and say you treated them as vendored — but never use "it's probably vendored" as an excuse to skip first-party code.

Work in this order:

1. **Get the lay of the land.** Look at the file tree, the languages present, the size, and the dependency manifests (`package.json`, `requirements.txt`, `go.mod`, `Cargo.toml`, `*.csproj`, `pom.xml`, `Makefile`, etc.). Read the README and any docs. Form a hypothesis about what the project is. Run the metrics script now to get real counts to anchor the report and dashboard:

   ```
   python "<skill-dir>/scripts/count_loc.py" <repo-path>
   ```

   It prints a per-language table (files, code, comment, blank, total) and the totals; add `--json` if you want to lift the numbers programmatically. Use these measured figures — file count, language count, per-language LOC — rather than eyeballing them, so the "how big is this" claims are accurate.

2. **Find the spine.** Locate entry points (`main`, `index`, `app`, CLI definitions, server bootstraps, exported library surface, `Dockerfile`/`docker-compose`, CI workflows). These tell you how the thing is actually run and what it exposes. Trace outward from there.

3. **Read every source file in full.** Go through the entire tree — core logic, request handlers, auth, data access, crypto, file/network/subprocess I/O, config loading, every module, plus the tests, prompt/text assets, scripts, and CI files. Prioritize the spine and the security-relevant hot spots first (that is where the most important findings usually are), but keep going until you have read everything. Grep is a way to *locate* things fast, not a substitute for reading — a grep hit tells you where to look, then read the surrounding file. On a large repo this is a lot of reading; do it anyway, in batches, tracking which files you have covered so none are missed.

   As you read, keep a running inventory of two things the user specifically cares about: **networking** (see "Networking & cryptography" below) and **cryptography**. These cut across the codebase and are easy to miss if you only think in terms of features.

4. **Run the secret scan** (see below) across the whole tree, including config, `.env*`, CI files, and history-adjacent files. This catches things a human reviewer skims past.

5. **Reconcile.** Where does the code do more, less, or something different than the docs claim? That gap is often the most useful thing in the report.

State your coverage honestly in the report. The target is **100% of source files read in full** — say so when you achieve it (e.g. "all N files read in full"). If a repo is so large that a complete read is genuinely infeasible in the session, do not quietly sample: read as much as you can (spine + all security-relevant modules first), then tell the user plainly which files remain unread and offer to continue, rather than presenting partial coverage as complete. Always list binary/generated files that were excluded and note they were not disassembled.

### Very large repos: chunk the full read across turns

A single session cannot hold every line of a large codebase in context — tens of thousands of lines will exhaust the window before you finish. That does **not** lower the every-file bar; it changes the *pacing*. When `count_loc.py` shows the repo is big (rough rule of thumb: more than ~10–15k lines of code, or more than ~50 source files), plan a **chunked complete read** instead of trying to swallow it whole:

1. **Build a coverage checklist.** Take the file manifest (the `find`/`count_loc.py` listing) and treat it as a to-do list of every source file. Persist it if useful — e.g. write `coverage.md` (or a checklist in the workspace) marking each file `read` / `pending`, so progress survives across turns and nothing is silently skipped.
2. **Read in prioritized batches.** Order: the spine and security-relevant modules first (entry points, auth, config, anything doing TLS/network/crypto/`eval`/`exec`/`subprocess`/deserialization/file I/O), then the rest. Read a batch, extract the findings and facts you need into your notes/report, tick those files off, and move on. You are mining each file for what matters, not memorizing it.
3. **Confirm what data files are, then move on.** Large generated/data blobs that happen to be text (a checked-in knowledge-base JSON, embeddings dumps, fixtures) should be sampled enough to confirm what they are and noted as data — do not read every line of a 7k-line generated JSON as if it were logic. First-party code is never treated this way.
4. **Be explicit about state.** If you run out of room before the checklist is exhausted, say so precisely: "read in full: X of N files (list/attach the checklist); remaining Y files pending (list them)" — and offer to continue in the next turn. When re-invoked to continue, resume from the checklist rather than starting over. Only claim "100% / all files read" when the checklist is genuinely complete.
5. **Bound the security coverage with a whole-tree sink grep.** When the repo is too large to finish reading in one engagement, you can still make a *provable* statement about the security surface: grep the entire tree (not just the files you've read) for every code-execution / deserialization / network sink — e.g. `grep -rnE 'eval\(|exec\(|compile\(|subprocess|os\.system|os\.popen|pickle|marshal|__import__|shell=True|verify=False|requests\.|urllib|socket\.|yaml\.load|ctypes|CreateProcess|ShellExecute'` (adapt per language). Cross-check every hit against your read list. If every sink lands in a file you've already read in full, you can state with confidence that **the remaining unread files are sink-free** and the security assessment is complete even though line-by-line coverage isn't 100%. This turns "I ran out of turns" into a defensible coverage claim; put the grep and its result in the Methodology/Coverage section. (It bounds *security* coverage, not the full read — first-party logic still deserves reading when time allows.)

The point is that "read everything" is achieved by **completing the checklist over as many turns as it takes** — and where that is infeasible, by **proving the security surface is bounded** (step 5) rather than pretending one pass covered a repo it could not.

## Secret & credential scanning

Every codebase analysis needs the same regex-and-triage secret sweep, so a script is bundled to do it consistently instead of reinventing it each time. Run it against the repo root:

```
python "<skill-dir>/scripts/scan_secrets.py" <repo-path>
```

It walks the tree (skipping `.git`, `node_modules`, and other vendored/binary dirs), matches known high-signal secret formats (AWS keys, private keys, **certificates, public/SSH/PGP keys, PGP signatures**, GitHub/Slack/Stripe/Google tokens, JWTs, connection strings, generic `password=`/`api_key=` assignments, `.env` values), and prints `file:line: <finding type>` with the matched span truncated.

**Also enumerate cryptographic material — digital signatures, certificates, and keys.** The scanner catches PEM/PGP/SSH blocks in *text* files, but binary key stores are skipped by the content scan, so also sweep the tree by name/extension for cert and key artifacts — e.g. `find` for `*.pem *.crt *.cer *.der *.p7b *.p7s *.pfx *.p12 *.jks *.keystore *.key *.pub *.asc *.gpg *.sig` — plus code-signing hints (Authenticode, `signtool`, notarization, a `*.snk` strong-name key, a signed manifest). For each item, say **what it is** and **whether it's sensitive** — a live **private key** or pinned client cert is a finding; a public **CA bundle** or test fixture is benign. Report the inventory in the report's **Operating Footprint → Certificates, keys & signatures** line, and cross-reference any private key or embedded credential into Potential Vulnerabilities.

The script is a *net*, not a verdict. It over-flags on purpose — test fixtures, example configs, and placeholder values will match. Your job is to triage each hit: is it a real, live-looking secret committed to the repo, an obvious dummy (`password = "changeme"`, `sk_test_...`), or a false positive? Report the real ones prominently with `file:line`; briefly note the placeholders; drop the noise. Also do your own reading — the script won't catch a credential built from concatenated strings or an unusual custom format.

## What to look for in the security pass

Think like an attacker reading the code. The high-value categories, roughly in order of how often they bite:

- **Hardcoded secrets** — passwords, API keys, tokens, private keys, connection strings with embedded credentials. (The scanner seeds this; verify and expand by reading.)
- **Injection** — SQL/NoSQL built by string concatenation, shell/command execution with untrusted input (`os.system`, `exec`, `subprocess` with `shell=True`, backticks, `eval`), template injection, LDAP/XPath.
- **Deserialization & parsing of untrusted data** — `pickle`, `yaml.load` (unsafe), `Marshal`, XML external entities (XXE), unbounded parsers.
- **Path traversal / arbitrary file access** — user-controlled paths joined without validation, unrestricted upload/download.
- **Weak or misused crypto** — MD5/SHA1 for passwords, hardcoded IVs/keys, `Math.random()` for tokens, disabled TLS verification, `verify=False`.
- **AuthN/AuthZ gaps** — missing access checks, JWT `none` alg, secrets compared non-constant-time, default/backdoor credentials.
- **SSRF / open redirects / CORS** — user-controlled URLs fetched server-side, `Access-Control-Allow-Origin: *` with credentials.
- **Dependency & supply-chain risk** — obviously outdated or known-vulnerable pinned versions, install scripts that fetch-and-execute, suspicious postinstall hooks.
- **Info leakage** — verbose errors/stack traces returned to clients, secrets in logs, debug endpoints left enabled.

Rate each finding by rough severity (Critical / High / Medium / Low) and, crucially, give enough context (`file:line`, the offending snippet, and *why* it's exploitable or under what conditions) that the user can verify it themselves. Distinguish confirmed issues from "worth a look" suspicions — don't inflate uncertain findings into confirmed CVEs, and don't bury a real leaked key under a pile of hypotheticals.

## Networking & cryptography

The user explicitly wants these two capabilities called out, because they define a program's attack surface and its trust model — what it talks to, and how it protects data. Treat them as first-class findings, not afterthoughts, and always include the section even if the answer is "none found" (that itself is informative).

**Networking — what does this code talk to, and how?** Look for:
- Outbound clients (HTTP/S libraries, gRPC, raw sockets, WebSockets, message queues, DB drivers) and the endpoints/hosts/ports they reach — hardcoded URLs and IPs are worth listing explicitly.
- Inbound servers/listeners (web frameworks, `listen()`/`bind()`, exposed ports, routes/endpoints) — what the program exposes and on which interface (localhost vs `0.0.0.0`).
- Protocols and transport security: is traffic TLS-protected, is certificate verification on, are there plaintext protocols (HTTP, FTP, Telnet) where sensitive data flows?
- Auth over the wire: how requests are authenticated (API keys, bearer tokens, mTLS, basic auth), and whether credentials traverse insecure channels.
- **Network signatures / indicators.** Beyond *what* it talks to, capture the fingerprints that would identify this app's traffic or presence to a defender — the raw material for a detection rule or IOC list: hardcoded hostnames, IPs, ports, and URL paths; distinctive `User-Agent` strings or custom HTTP headers; fixed request bodies or magic bytes in a custom protocol; DNS names and beaconing intervals; TLS/certificate peculiarities (pinned certs, self-signed, unusual JA3-ish client behaviour). If the app does no networking, there are no network signatures — but note any **host-based** signatures instead (named mutexes/events, fixed file paths, registry keys, service names, window titles), since those play the same identification role locally.

**Cryptography — what primitives are used, and are they used correctly?** Look for:
- Which libraries/primitives appear (OpenSSL, libsodium, `cryptography`, WebCrypto, JCA, Go `crypto/*`, platform APIs like CNG/CryptoAPI) and for what: encryption, signing, hashing, MAC, key exchange, random generation.
- Algorithms and modes (AES-GCM vs AES-ECB, RSA, ECDSA, ChaCha20, SHA-256 vs MD5/SHA1), key sizes, and how keys/IVs/salts are generated and stored.
- Password handling: is a real KDF used (bcrypt/scrypt/argon2/PBKDF2) or a bare/unsalted hash?
- Randomness source: CSPRNG vs a predictable PRNG for security-sensitive values.

Where crypto or networking is misused, the finding belongs in **both** this inventory (as a capability) and the vulnerability section (as a risk) — e.g. "uses AES-ECB" is a capability worth noting and a Medium/High weakness worth flagging.

## Deliverables

The deliverable is **one single, self-contained HTML evaluation report and one matching PDF** — nothing else. Everything collates into that one document: the executive summary, metrics, architecture, capabilities, system-interaction surface, networking/crypto, dependencies, the interactive call tree, the findings table, the replication assessment, and a methodology/reproduction appendix. Do **not** ship a scattering of separate dashboard / call-graph / markdown files as the deliverable — one report, one PDF.

- **Build the single HTML from the bundled scaffold** `assets/report-template.html`. It already contains the styling, the section skeleton (with a table of contents), the embedded interactive **call tree** engine, and a **Methodology & Reproduction** appendix. Fill every `{{PLACEHOLDER}}` and `<!-- SLOT -->` with the real analysis, and replace the call-tree `GRAPH` object with the functions/edges you traced. Save as `CODE-ANALYSIS.html`.
- **Render the matching PDF from that exact HTML** — never hand-build a separate PDF, so the two can never disagree:
  ```
  python "<skill-dir>/scripts/html_to_pdf.py" <path>/CODE-ANALYSIS.html <path>/CODE-ANALYSIS.pdf
  ```
  It uses headless Chrome/Edge/Chromium (falls back to `weasyprint`); if neither exists it says so — then deliver the HTML and tell the user to "Print → Save as PDF". The template's `@media print` rules give a clean light PDF with sections kept intact across page breaks.
- **Frame it as a professional evaluation** and make it **reproducible**: the Methodology & Reproduction section must give an engineer enough to re-derive every number and finding — the environment, the exact commands (`count_loc.py`, `scan_secrets.py`, how the code was obtained), the coverage (which files were read in full), and how to build/verify the target if applicable. Measured figures come from the tools, not estimates.

You may still keep a **Markdown working note** (`CODE-ANALYSIS.md`) as an internal scratchpad for your own thinking, and print a condensed summary in the chat — but the thing you deliver is the single HTML + its PDF. (The older standalone `dashboard-template.html` and `callgraph-template.html` remain in `assets/` as components, but the consolidated `report-template.html` is what you ship.)

## Report structure

The single HTML report collates the sections below (they map to the scaffold in `report-template.html`). Author them as report prose/tables, not as a terse dashboard:

```
Code Evaluation: <project name>   (cover: risk badge, severity counts, source, coverage, date)

1. Executive summary — what it is, overall risk, the one thing to act on.

## Overview & metrics
Measured file/LOC/language counts and dependency/secret-hit counts; one tight paragraph of what the project is and how much was reviewed.

## Architecture & Key Artifacts
How the project is organized and how it runs. Entry points, core modules, the notable files a new engineer must know, build/deploy setup. A short directory-level orientation is welcome. Reference real paths.

## Core Features & Capabilities
Open with a tight bulleted list of the **core features** — the handful of things this app exists to do, as a user would name them.

Then, for each capability, **describe how it is achieved in the code** — name the concrete mechanism, not just the outcome. Point to the specific API set, library, framework, or syscalls, and the functions/files that call them. For example: "Cryptography is implemented through calls to the Windows CNG API set (`BCryptEncrypt`/`BCryptGenRandom` in `crypto.c`)"; "Networking is done with the `requests` library hitting `api.example.com` from `client.py`"; "Persistence is achieved by writing a Run key via the registry API (`RegSetValueEx` in `install.c`)". This turns the capability list into a map of *how the program actually touches the world*, which is far more useful than a paraphrase of the README.

Cast a wide net — this is not only about security bugs. Trace and report the core functions behind every way the program interacts with the system, especially:
- **Networking** — the client/server libraries and the hosts/ports/endpoints they reach.
- **System & registry modification** — registry reads/writes, environment/service/scheduled-task changes, driver or kernel interaction, privilege/token operations.
- **File & filesystem access** — what it reads, writes, creates, or deletes, and where (config, temp, user data, system paths).
- **Process & OS control** — spawning processes, injecting, loading libraries, IPC (named pipes/events/mutexes/sockets), OS queries.
- **Sensitive-system access** — microphone/camera/screen capture, keystrokes, credentials/keychain, location, clipboard, or any other privacy- or security-sensitive resource.
- **Cryptography** — the primitives/API set used and for what.

Note where reality diverges from the README.

## Dependencies & Integrations
Key third-party libraries, external services/APIs it talks to, and how it's configured (env vars, config files, secrets it expects).

## Operating Footprint
What the software looks like once **deployed and running** — the view an operator or defender needs to recognise it on a live system:
  - **Files deployed** — every artifact that lands on disk and where: the executable(s), DLLs/shared objects, config/data files, models, install directories, and any registry-installed paths. Note whether it's a single self-contained binary or a tree of files, and whether an installer/uninstaller is involved.
  - **External libraries required** — the runtime dependencies needed to actually run: system libraries (Windows DLLs, glibc, …), bundled/third-party libraries, and language runtimes (.NET, Python, JVM, Node). Distinguish in-box/OS-provided from things that must be installed.
  - **Runtime identity** — this depends on the artifact type:
    - For a standalone **executable**: the probable **process name** (e.g. `audior.exe`), whether it's foreground/console/service/daemon, and any **named pipes** or named kernel objects (mutexes, events, shared memory) it creates — these are strong host IOCs.
    - For a **DLL / shared object / plugin / extension / script module** (which cannot run on its own): the probable **host process** that loads it — e.g. an IDA plugin runs inside `ida64.exe`, a browser extension inside the browser, a Python module inside `python.exe`, an injected DLL inside its target, a `.so` inside whatever links it.
Base this on the code and build output (`build.bat`/`Makefile`/manifests, the linked libraries, `CreateNamedPipe`/`CreateEvent`/`CreateMutex` calls, plugin entry points). Where you are inferring rather than certain (e.g. a likely process name), say "probable".

## Networking & Cryptography
The inventory from the pass above. Two clearly labeled parts:
  - **Networking** — outbound clients and the hosts/ports/endpoints they reach, inbound listeners and exposed ports/routes, protocols, and transport security (TLS on/off, cert verification). List hardcoded URLs/IPs. If the project does no networking, say so plainly.
  - **Cryptography** — primitives/libraries in use and what for (encryption, hashing, signing, key exchange, RNG), algorithms/modes/key sizes, password KDF handling, and randomness source. If there's no cryptography, say so.
  - **Network signatures / indicators** — the fingerprints that would identify this app to a defender: hardcoded hosts/IPs/ports/URL paths, `User-Agent`s and custom headers, custom-protocol magic bytes, DNS names, TLS quirks. If it does no networking, say "none" and list any **host-based** signatures instead (named mutexes/events, fixed paths, registry keys, service/window names).
Cross-reference anything misused here into the Potential Vulnerabilities section.

## Potential Vulnerabilities
The security section. Lead with a one-line risk posture. Then list findings, most severe first, each with: severity, `file:line`, a snippet, and why it matters. Separate:
  - **Embedded credentials / secrets** — anything sensitive committed in plaintext.
  - **Code vulnerabilities** — injection, unsafe deserialization, weak crypto, auth gaps, etc.
  - **Other observations** — lower-confidence smells, dependency risk, hardening gaps.
If you found nothing credible in a category, say so explicitly — "no hardcoded secrets found" is a useful result.

## Replication & Feature-Match Assessment
An engineer's estimate of how hard it would be to rebuild this app or match its features from scratch — the "could a competitor clone this?" question. Give:
  - **Overall difficulty** — a rating (Trivial / Low / Moderate / High / Very High) and a rough effort band (e.g. "a weekend", "1–2 weeks for one dev", "a small team for months").
  - **What's commodity** — the parts that are boilerplate or a solved problem (CLI parsing, CRUD, standard file formats, well-trodden library calls) and could be reproduced quickly.
  - **What's hard / differentiated** — the genuine engineering: tricky algorithms, hard-won correctness (concurrency, real-time, numerical), non-obvious platform/API interop, performance work, accumulated edge-case handling, proprietary data or models, scale.
  - **Expertise required** — the specific skills a cloner needs (e.g. "WASAPI/COM internals", "distributed systems", "ML"), since rare expertise is itself a moat.
  - **Moat** — is there anything that actually prevents replication (network effects, data, patents, secret sauce), or is the barrier purely effort and know-how? Base this on the code, and be honest: many apps are mostly commodity glue, and saying so is the useful answer.

## Call Tree
The embedded interactive call tree (see "The call tree" below) plus one sentence orienting the reader to it.

## Methodology & Reproduction
Enough for an engineer to re-derive every number and finding: the environment, the bundled tools used, the **exact commands** run (obtaining the code, `count_loc.py`, `scan_secrets.py`), the **coverage** (which files were read in full, what was excluded), and how to **build/verify the target** if it compiles or runs. This section is what makes the report a professional, reproducible evaluation rather than an opinion.

## Conclusion
A few sentences: overall assessment, the single most important thing to act on, and honest caveats about coverage.
```

Adapt the depth to the repo — a 200-line utility doesn't need the same ceremony as a monorepo — but keep the section order so the security content is always in the same, findable place.

## Building the report

Fill `assets/report-template.html` and save it as `CODE-ANALYSIS.html`. It is one professional evaluation document — a cover band (project, risk badge, severity counts, source, coverage, date), a table of contents, and the twelve sections above, all self-contained (inline CSS/JS, no CDNs), theme-aware, and print-styled.

Non-negotiables:
- **Fully self-contained** — inline everything; it must open from a local file with no network (these reports often cover offline/air-gapped or sensitive code).
- **Lead with risk** — the cover carries the one-line risk posture and the colored Critical/High/Medium/Low counts, so the eye lands on the worst thing first.
- **Measured, not eyeballed** — file/LOC/language counts come from `count_loc.py`; secret-hit count from `scan_secrets.py`. Include the per-language breakdown.
- **Substance over filler** — real capabilities framed by mechanism, real findings with `file:line`, real reproduction commands. This is an evaluation an engineer will act on.

### The call tree

The report embeds an interactive **hierarchical call tree**, laid out horizontally like a debugger/disassembler (e.g. IDA Pro): the entry point on the left, callees expanding right through elbow connectors, each node's subtree collapsible by clicking, pan/zoom/Fit. Because this skill is **read-only static analysis** (never execute the target), it is built from **static call relationships you traced while reading** — who calls whom — not runtime tracing.

Populate its `GRAPH` object (inside the report's embedded `<script>`): node schema `{id, label, group, weight, module}` where `group` ∈ `entry|core|network|crypto|io|ui|util|external` (drives colour) and `weight` 1–4; edge schema `{from, to}` with direction **caller → callee**; set `root` to the entry point. Pick the **key functions** — not just security-relevant ones, but the core functions behind every essential capability and system interaction: entry points/dispatchers, and whatever does **networking**, **registry/system modification**, **file access**, **process/OS control**, **sensitive-system access**, and **crypto**, plus anything in the findings. Aim for a legible **10–40 nodes**; every edge must be a call you actually saw in the source — a smaller tree you can vouch for beats a large speculative one.

### Then render and deliver

Render the PDF from the finished HTML (`html_to_pdf.py`, above), verify it produced pages, then deliver **both files** — the interactive `CODE-ANALYSIS.html` and the matching `CODE-ANALYSIS.pdf` — and print a short summary in the chat.

## Scope & honesty

- This is **analysis, read-only**. Don't edit, "fix", or run untrusted code from the repo. Reading source and running the bundled scanner is fine; executing the target project's own scripts is not, unless the user explicitly asks and understands the risk.
- Don't fabricate findings to look thorough. A clean bill of health, honestly reached, is a valid and valuable outcome.
- You are not a substitute for a full pentest or a dedicated SAST tool; say so when the stakes warrant it. Flag the things a sharp reviewer would catch on a careful read, and be clear about the limits of that.
- **Reporting a capability is not the same as helping build or hide one.** Describing what malicious code does (persistence, injection, exfiltration, C2 signatures) — including at mechanism level, for a defender's or researcher's understanding — is the point of this skill, and that holds even when the sample is clearly malware. But if the target is obviously malicious (RAT/stealer/ransomware/C2) and the user's ask shifts from *understanding/detecting* it to *improving* it — evading the very detections/signatures the report just catalogued, weaponizing a capability further, or using the "Replication & Feature-Match Assessment" as a build guide for cloning malicious functionality — that request falls outside this skill. Finish or hand over the analysis itself, decline only the evasion/build-it-for-me ask, and say plainly why.
