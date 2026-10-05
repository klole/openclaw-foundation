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
python3 /absolute/path/openclaw-foundation-2.1.0-rc.1.zip init --config /absolute/path/company.json --root /absolute/path/new-company
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

The running foundation service checks GitHub for newer releases once a day. It shows an update notice in HQ and sends one local COS inbox notice per version. An operator approves installation after reviewing the release notes. The default stable channel ignores drafts and previews. An independent daily host checker can run when the model worker is stopped.

```sh
python3 /absolute/path/new-company/foundation check-updates --force
python3 /absolute/path/new-company/foundation fetch-update
```

Fetch verifies the archive and prints exact preview/apply commands. Stop the worker, save a private backup, preview, then apply. Company facts, memories, custom agents and runtime records are preserved; edited managed files cause conflicts. Native provision/restart and readiness checks remain separate. See [updates](updates.md) for stable/preview channels, daily host scheduling, recovery and rollout.

## Maintain the foundation

Work on an isolated branch and open a pull request. Run `python3 -m unittest discover -s foundation/tests -v`, obtain independent review, then build a release under a new immutable version. Retained deterministic research gates have their own source provenance in `backend/provenance.json`.

Source-specific privacy exclusions stay in the maintainer source and are not shipped. The runtime retains generic credential detection. The release is executable code: obtain the archive and checksum through a trusted channel. Checksums detect corruption; they do not authenticate its publisher. Candidate archives remain review candidates until their PR is approved. No live provider turn or real PR merge is implied by offline tests.
