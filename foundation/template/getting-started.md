# OpenClaw company foundation

A portable, versioned foundation for macOS and Linux, with a company-neutral operating structure. The package includes runnable Python services, generic agent roles and department blueprints. Company facts, credentials, history, integrations and business teams start empty. Python 3.9+ and the standard library are sufficient for the backend; agent turns additionally need a configured OpenClaw gateway.

## Included versus configured per company

| Layer | Ships with the foundation | Fill or connect at installation |
|---|---|---|
| Operating core | Company COS, systems engineer, operations watcher, context/Bible keeper, builder/trainer, change reviewer, judge, release challenger | Human names, available models, budget and notification preferences |
| Context helpers | Metrics worker, current-state worker, daily recorder | Actual source definitions, metric periods, owners, freshness and company rules |
| Research | Researcher, director, challenger, breaker, planner, verifier; saved sources, deterministic quote/number/arithmetic/plan checks | Evidence exports; approved search adapters; optional verifier model families |
| Optional | Tool Scout; portfolio COS blueprint | Specific tools to investigate; approved cross-company broker |
| Business organization | Manager, strategist, specialist, worker, checker and proactive role blueprints | Departments, goals, plans, held-out cases, required platform tools and team card |
| Services | Durable delegation/hiring/research queues, owner approvals, file bridge, monitor, adaptive wakes, scheduled jobs, budget reservations, provisioning, HQ, hygiene, backups and recovery | Provider sign-ins, gateway/profile, repository check commands and independent merger identity |

There are 18 on-demand seats, plus the optional portfolio COS. Domain-specific ecommerce, marketing, sales, finance and customer-facing agents are created from blueprints when a company needs them. No existing business team, campaigns, accounts, products, metrics or memory are cloned.

## Create a copy

Fill `company.example.json` with company identity, owner, timezone, names and model routes. The archive installs directly:

```sh
python3 /absolute/path/openclaw-foundation-2.0.1.zip init --config /absolute/path/company.json --root /absolute/path/new-company
python3 /absolute/path/new-company/foundation doctor
```

Then follow [setup](setup.md). Initialization changes no live OpenClaw config and starts no paid calls or schedules. `config/backend.json` controls paths, transport, budgets, thresholds, research reviewers, wakes and configured repositories. The backend works beside an existing house on the Mac Mini or independently on another host; there is no need to modify the original house's business registries.

## Run and inspect

```sh
python3 /absolute/path/new-company/foundation collect
python3 /absolute/path/new-company/foundation submit --kind work --input /absolute/path/work.json
python3 /absolute/path/new-company/foundation tick --steps 10
python3 /absolute/path/new-company/foundation hq
python3 /absolute/path/new-company/foundation status
```

Native calls remain disabled until provisioning and target credentials are ready. Automated tests use scripted providers and no model spend. Agents submit validated workspace requests rather than receiving general shell access. The operator CLI handles authorization, deployment and recovery. See [services](playbooks/service-wiring.md) and [runbook](operations.md) for the actual workflows.

## Update a copy

Stop its foundation worker and save a private backup, then preview/apply a trusted new archive:

```sh
python3 /absolute/path/new-company/foundation update --bundle /absolute/path/openclaw-foundation-2.1.0.zip
python3 /absolute/path/new-company/foundation update --bundle /absolute/path/openclaw-foundation-2.1.0.zip --apply
python3 /absolute/path/new-company/foundation migrate --apply
python3 /absolute/path/new-company/foundation provision
python3 /absolute/path/new-company/foundation provision --apply
```

Managed edits cause conflicts rather than silent overwrites. Company data, custom agents, memories and runtime queues are preserved. Gateway provisioning has its own validated preview and compare-before-write rollback receipt. Restart the target gateway after changed agent config, verify fresh seat readbacks, then restart the worker. [Updates](updates.md) explains upgrades, rollback and recovery.

## Maintain the foundation

Work on an isolated branch and open a pull request. Run `python3 -m unittest discover -s foundation/tests -v`, obtain independent review, then build a release under a new immutable version. Retained deterministic research gates have their own source provenance in `backend/provenance.json`.

Source-specific privacy exclusions stay in the maintainer source and are not shipped. The runtime retains generic credential detection. The release is executable code: obtain the archive and checksum through a trusted channel. Checksums detect corruption; they do not authenticate its publisher. Candidate archives remain review candidates until their PR is approved. No live provider turn or real PR merge is implied by offline tests.
