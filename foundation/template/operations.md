# Operator runbook

Run `python3 /absolute/path/company/foundation --help` for commands. The installed launcher supplies its root automatically. All JSON input/config is local UTF-8; secrets belong to the target credential store. This runbook assumes a dedicated company gateway already configured as in setup.md.

## Work, approvals, failure and hiring

A work request is a JSON file:

```json
{"goal":"Reconcile the current goal sheet","maker":"plumber","checker":"push-queue"}
```

`submit --kind work --input <file>` returns a job ID. `tick --job <id> --steps 10` advances bounded stages, and `status --job <id>` shows evidence/reviews. The persistent worker performs one stage per poll. COS hands off a bounded brief, maker submits an artifact, checker independently returns PASS/FIX/HUMAN REVIEW, and COS closes only after PASS. Public/spend requests set public/spend_usd and always require approval. These flags authorize a reviewed task, not undeclared public tools or paid plans.

`approve --job <id> --decision approve|hold|deny [--expires <ISO-time>]` records operator authorization bound to the exact input. Hiring sign-off is requested after the role and tests are built. It binds the tested role and exact helper list; an early brief approval does not count as final build sign-off. Each covered helper still follows the testing/COS/provision/onboarding sequence. Changed scope needs a new proposal. Manager-plan approval is additionally bound to the actual completed plan. A deny leaves work blocked; it never starts a task. Agent workspace requests cannot impersonate operator authorization.

A transport/stage failure raises an incident, retries with backoff, then dead-letters at the attempt cap. `retry --job <id>` is an explicit operator action after repairing and inspecting evidence. A lost lease becomes needs-attention rather than blindly duplicating an uncertain side effect. Monitor recovery requires a successful observed stage/source readback. After a token reservation overrun, verify provider limits and bounds; resolve the budget incident using `incident-resolve` with a real proof path before resuming.

A hire request:

```json
{"goal":"Create a specialist for a bounded operating task","requirements":["Cite source evidence"],"seat":{"id":"operations-specialist","title":"Operations Specialist","type":"specialized","reports_to":"cos","model_class":"worker","spawn":[],"needs":[]}}
```

Submit `--kind hire` and advance it through tests/reviews. It holds at final install until the operator approves the concrete build (status shows the role, tests, helpers and reasoned budget). Then advance it to ready-to-provision. Tool dependencies must have current proofs. Trainer preserves requirements and supplies training cases; the independent challenger supplies different held-out cases. Pre-signoff checks review the proposed role and test design. Actual seat answers are tested after provisioning, before readiness is reported. Challenge, judge and change review run under distinct roles. The role is stored in custom/ with qualification evidence. It stops at ready-to-provision. Stop the worker, review `activate --job <id>`, then add `--apply`. Native activation renders, validates/provisions and queues held-out onboarding. Restart the target gateway after new native seats, then resume ticks. Fixture activation with native disabled proves the pipeline only and does not claim live readiness. Extra tool requests remain blocked pending reviewed adapter grants. A manager also needs a research plan, then `approve` after the plan is done and `manager-plan --job <plan-id> --apply`.

## Research and recurring watches

`submit --kind research` accepts goal, mode (answer/compare/plan), card (goal_exact/unit/baseline/constraints/ladder), and saved sources (id, class, text or installation-relative path, URL and as_of). The goal must match the card exactly. Sources are frozen and hashed; use approved read-only exports or a separately reviewed search collector to save evidence. Built-in research has no arbitrary web scraper or paid search connection. Agent bridge requests can read only their own work files or context exports explicitly published in company/context/sources.json (sources/research_sources). Published records determine evidence class. Agent-authored notes are tertiary; they cannot assert primary measurement provenance or read private config, secrets or another workspace. Operator research inputs remain the trusted import surface.

Example input:

```json
{"goal":"Understand the current operating baseline","mode":"answer","card":{"goal_exact":"Understand the current operating baseline","unit":"verified outcomes","baseline":"unknown"},"sources":[{"id":"approved-record","class":"internal_record","path":"company/context/research-source.txt","as_of":"2026-01-01"}]}
```

Quote presence, numbers, arithmetic, duplicate evidence, host concentration and plan constraints are checked by code. Judge and breaker review claims. Readiness requires supported claims and no blocking challenger. Plan mode adds the deterministic plan gate, fresh verifier turns and release challenge. Set research.verifier_models and required_model_families to require diverse model providers for plan verification. Results, frozen sources, context and receipts stay under state/research and state/artifacts. Gaps remain explicit; rejected evidence never becomes a supported claim.

`config/automations.json` is executable scheduler configuration, disabled by default. Example:

```json
{"enabled":false,"jobs":[{"id":"baseline-watch","every_seconds":86400,"kind":"research","payload":{"goal":"Understand the current operating baseline","mode":"answer","card":{"goal_exact":"Understand the current operating baseline","unit":"verified outcomes","baseline":"unknown"},"sources":[{"id":"approved-record","class":"internal_record","path":"company/context/research-source.txt"}]}}]}
```

The source file is frozen afresh at each run. Recurring jobs do not overlap unresolved earlier jobs; failed/held jobs stop that cadence until handled. `schedule` previews current execution by queuing due jobs; `status` shows them. It never buys an adapter or bypasses per-job/company caps. Results are private inbox/HQ updates; no external notification channel is assumed.

## Context and Bible

`collect` reconciles configured typed fact exports and writes current.json, INDEX.md, CHANGES.json, conflicts.md and dated history. It copies current context into seat workspaces. `packet --goal <exact-goal>` creates a bounded, hashed context packet. Source removal/failure carries previous values as stale with a gap. `monitor` routes unreadable sources and stalled jobs; fresh source health verifies recovery.

Workspace bridge actions bible-note/bible-read/bible-propose support the keeper without cross-workspace file grants. Notes require source/as_of/text and start unverified. The keeper can propose a bounded snapshot plus typed facts. That creates a librarian work job with independent review and COS closure. The service files completed verified proposals by default; set context.auto_file_verified_bible false for manual filing. Owner approval is added only if this company explicitly enables context.bible_requires_owner. `bible-apply --job <id>` previews the exact completed proposal, and `--apply` files it while preserving original records. Do not add uncited facts or silently overwrite owner decisions. After snapshot changes, stop the worker and render instructions. Facts/history remain installation-owned across updates.

## Native file proofs and external tools

Write an unpredictable UTF-8 fixture under a seat's work/ folder. Submit:

```json
{"goal":"Verify actual workspace file access","seat":"plumber","tool":"workspace-read-plumber","fixture":{"type":"read-file","path":"work/proof.txt"}}
```

The agent must return exact observed bytes; the expected value is not sent in its prompt. Code compares readback and then a distinct reviewer checks evidence. Proofs have dates/seat/native provenance. Each target's external adapters need their own deterministic verifier and scoped permissions. Read-file proof is not evidence of platform access, publishing, credential safety or general model quality.

## Repository release gate

Configure repositories in backend.json using an absolute clean task checkout, literal command arrays, GitHub owner/repo, gh_binary, timeout and an independent merger_login. Example check: `["python3","-m","unittest","discover","-s","tests"]`. Do not configure arbitrary commands supplied by agent output. Submit a gate job with goal/repository/head (full SHA)/pr/maker/reviewer/artifact. The producer cannot review its own change. Current owner authorization is required before gate execution and explicit `merge --job <id> --apply` rechecks clean exact head, tests, PR head and independent login. It uses match-head-commit; a changed head invalidates release. No real PR merge is run by the clean-install tests.

## Startup, HQ and hygiene

`serve --once` runs bridge/context/monitor/wake/schedule and one queued stage. `serve --poll 30` runs persistently under a singleton lock. Set native.env_path if OpenClaw/Node/provider helpers need directories outside the supervisor's default PATH. A service cycle writes service-health.json and refreshes generated/hq.html. `hq` also refreshes the escaped local dashboard on demand; opening it reveals private company work. It is a local snapshot, without an unauthenticated network server.

`service-files --python <absolute-python>` generates startup files but does not activate them. On macOS, review and copy generated/service.launchd.plist into the company user's ~/Library/LaunchAgents under its Label, then use launchctl bootstrap/bootout on that plist. On Linux, review/copy generated/service.systemd.unit into the company user's ~/.config/systemd/user/ as openclaw-foundation-<company-id>.service, then daemon-reload and enable --now; stop it before upgrades. Use the dedicated user's normal supervisor procedures, not another company's service labels. Both profiles run the same Python backend.

Wake is disabled by default. When enabled, managers/COS use a seven-level cadence based on goal/inbox work; specialists stop when empty and control seats stay request-only. Manual workers/checkers use type control. Inbox items consumed by a completed wake job are archived, so a stale inbox does not wake a specialist forever. Managers with no approved plan do not proactively wake. A GOALS.md line `Wake: OFF` pauses that seat; the seven named modes can also be selected there. URGENT expires after two hours without an updated goal sheet. Cadence values are configurable within the 5-minute/12-hour bounds. Completed wakes do not feed their own inbox.

`hygiene` archives older memory/notes and retains originals. Oversized GOALS/OPEN sheets are flagged with an archived original for keeper reconciliation, not silently truncated. Per-day limits are in config/backend.json. `doctor` stays conservative until live target prerequisites are met.

## Backup and recovery

Stop the foundation worker and dedicated gateway before including native state. `backup --output <private-archive> --native` includes installation data plus the configured dedicated native config/state, sessions, provider auth and SQLite snapshots. It requires absolute existing native paths, refuses symlinks, preserves private file permissions and does not follow links into another company. Inspect any refused link and use the private host backup procedure for external broker material. This recovery archive contains credentials; keep it private and never use it to instantiate another company.

`restore --archive <file> --destination <fresh-company-root> --apply` restores only the application, with transport/wakes disabled. `restore-native --archive <file> --destination <fresh-profile-dir> --apply` restores the dedicated native config.json/state/ into a separate fresh location. Both default to preview and reject existing destinations and corrupt/unsafe entries. Configure the restored paths, render, provision, restart the dedicated gateway, rerun fresh proofs, then restart the worker. Separate OS, broker, tailnet, external platform and heavy-media state needs your host backup procedure.
