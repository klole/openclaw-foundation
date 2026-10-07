# Install on the Mac Mini or another host

## Files and ownership

The installation holds `.foundation/managed/` (versioned code, role sources and playbooks), `generated/` (roster, native proposal, HQ and startup files), `workspaces/<seat>/` (generated instructions plus mutable work and memory), `config/` (local choices), `company/` and `bible/` (local truth/history), `custom/` (local roles/agents), `state/` (durable queues, receipts and health), and `archive/` (retained originals). Updates own only managed sources and generated bootstrap/roster/native-fragment files. Config, records, jobs and work belong to this installation.

A fresh copy is created from the release archive. A recovery backup belongs to an existing company; it must never be used as a new company's template.

## Both host profiles

On the existing Mac Mini, use a fresh installation and dedicated company gateway/profile, preferably a separate OS user. This portable backend runs alongside the existing house and does not edit its registries, rules, tools or gateway. On another Mac or Linux host, install Python 3.9+ and OpenClaw from its official distribution and use the same archive. Startup files differ by OS; the service code and configuration do not.

Choose a free gateway port and verify the derived browser port range too. Keep company state, budgets and credentials separate. Sharing a machine is supported; workspace paths and a shared gateway are not strong tenant isolation. Existing `cos` IDs intentionally cause a provisioning collision. Use a dedicated gateway/profile rather than overwriting another company.

## Installation sequence

1. Fill company.example.json; run `init` from getting-started.md. Model classes are coordinator, coding, worker, reviewer and research. Empty models inherit target defaults; configure available provider/model IDs explicitly before testing. Provider credentials stay in the target OpenClaw state; the template never copies them.
2. Fill company/RULES.md and bible/SNAPSHOT.md. Start company context with empty facts, then configure read-only JSON exports as described in company-context.md. An export adapter needs no backend code edits: it publishes typed facts to an installation-relative file. Company-specific platform fetchers run under their approved credential broker outside generic role text.
3. Edit config/backend.json. Set `native.binary` to the target executable, `native.config_path` to an absolute **JSON** OpenClaw config, and `native.state_dir` to its private state directory. Point both config and state at the intended profile. The target config must use explicit `agents.entries`; convert an older list configuration separately before this installer touches it. Preserve target sign-ins, provider definitions and channels.
4. Run `render`, then `render --apply`. Run `provision` for a preview and `provision --apply` to validate a private candidate with the target CLI and register only this foundation's tracked seats. It preserves unrelated native settings, refuses ID collisions and external edits, and saves an exact native rollback receipt. It never restarts the gateway. Restart the dedicated gateway with its normal host supervisor.
5. Configure paid-call policy. Native calls are assumed paid unless you explicitly set `native.paid` false for a verified local/free transport. Default `paid_calls.enabled` is false. Set daily/per-turn reservation caps and provider-side spending/output limits before enabling native transport. The backend bounds turns, time, retries and token reservations; a USD reservation is not a provider billing guarantee. An unknown price requires a verified conservative reservation or keeping the brake closed.
6. Set `native.enabled` true only after the target is provisioned. Submit read-file proof jobs under the actual seats. Their exact readback is checked by code and then by an independent reviewer. Other platform adapters need deterministic readback verifiers and explicit per-seat grants; the built-in file proof does not prove a CRM, store, publishing or browser capability. Never weaken an agent's brief to pretend missing tools work.
7. Exercise delegation, checker FIX/PASS, a failed/stale context source, a denied public action, an approved hire, held-out onboarding, research, and recovery. `doctor` reports managed drift, registrations, recent native file proofs, budgets, source gaps and service heartbeat. Native provider quality and external adapter behavior require target checks; offline checks are not live-provider proof.
8. Configure startup with `service-files --python /absolute/path/python3`. Review the generated launchd plist or systemd user unit and install it using operations.md. Start one worker per root. Enable adaptive wakes and recurring jobs only for approved scopes. A manager also needs a verified, separately approved plan.

## Business roles and portfolio

Use the hiring command and blueprints to create a department after the owner provides its goal, requirements and tools. New seats are local `custom/agents/<id>/seat.json` and `role.md`. They survive foundation updates. Hires stop at ready-to-provision until the operator reviews and runs `activate --job <id> --apply`. Activation renders the role, provisions it when native transport is enabled, and queues held-out onboarding. A manager's first research plan needs its own owner approval before proactive work begins. Larger/growth builds propose useful helpers or a reason to reuse existing seats. One owner sign-off of the tested parent build covers exactly its proposed helpers. Activation files their separate build requests; each still gets independent tests, COS approval, reviewed provisioning and onboarding. Later additions need a new approved scope.

Alternatively fill a reviewed blueprint manually, for example:

```json
{"id":"operations-manager","title":"Operations Manager","type":"manager","reports_to":"cos","model_class":"coordinator","spawn":[],"declared_tools":["read","write"]}
```

Declared tools are granted exactly from the built-in safe file/memory set. Additional external tools require a reviewed adapter/provisioning extension. Manually authored agents still need held-out tests, tool proofs and plan approval; rendering alone is not onboarding.

Set portfolio true to add a portfolio COS reporting to the owner. Cross-company routing is a separately authorized broker with scoped routes and credentials. This package does not silently connect company gateways or centralize their private context.

## Release checker

Daily GitHub checks are enabled by default and run inside serve; they make no model calls and install nothing. Use updates.md to choose the stable or preview channel, generate an independent host checker, and fetch a verified release for owner-approved installation. Early candidates require the preview channel.

## Dot messaging

Optional remote messaging and reply events are configured with dots.md. Each owner uses a separate authenticated identity, and ChatGPT connection/consent is completed in the owner account.
