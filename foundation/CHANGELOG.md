# Changelog

## 2.2.0-rc.2

- Fix browser OAuth form submissions by preserving the origin header without exposing authorization query parameters in referrers.
- Allow the exact ChatGPT callback in the login form's content security policy and return through an explicit POST-to-GET redirect. Origin, CSRF, PKCE and owner scope checks remain enforced.
- Add a regression test covering browser login headers, rejected origins, invalid CSRF cookies and the authorization-code exchange. Preview pending independent review.

## 2.2.0-rc.1

- Add an optional invite-only remote MCP messaging bridge for Dots on macOS and Linux, with per-owner OAuth code/PKCE login, rotating refresh tokens, scoped agent access and durable task receipts.
- Add MCP Events subscriptions and signed reply notifications, public-address-pinned TLS callbacks, callback verification, filters, expiration, revocation and retry delivery.
- Add operator setup, owner creation/revocation, service files, health checks and an installed Foundation runtime adapter. Separate owners may use their own authenticated messaging adapters for an existing team.
- Add a GitHub-link setup prompt, private generated connection instructions and explicit account-consent/live-Dot verification steps. Live hosting and owner authorization remain required.
- Existing company data, updater preview/apply/rollback and action gates remain local. Preview pending independent review.

## 2.1.0-rc.1 — 2026-10-05

- Public, company-neutral source repository with clean history and reviewable changes.
- Daily GitHub release checks with stable/preview channels, one COS notice per version and an escaped HQ update panel.
- Verified archive download with checksums, GitHub asset digest checking, bounded HTTPS redirects and scoped private-repository token support.
- Owner-approved preview/apply/rollback; no automatic code execution, gateway changes or restarts from a release check.
- Daily launchd/systemd checker generators work independently of the model worker.
- CI on Python 3.9/3.13 and a draft-release workflow, plus offline updater regression checks.

## 2.0.1 — 2026-10-05

- Restricted agent research imports to scoped work files and explicitly published context exports; agent notes cannot assert primary measurement provenance.
- Included a regression check for private-file requests and renewed leases around multi-turn and repository stages.

## 2.0.0 — 2026-10-05

- Runnable configuration-based service layer for both macOS and Linux; no fixed business registry dependency.
- Durable delegation, hiring/onboarding, owner approvals, source-derived research checks, repo release/merge gates, context/Bible reconciliation, monitoring and scheduler.
- Added judge and release-challenger seats plus optional Tool Scout; exact declared file/memory tool grants.
- Workspace request/result bridge, private local HQ, launchd/systemd generators and bounded workspace hygiene.
- Application/native recovery archives, separate native config preview/apply/rollback, additive state migrations and conservative readiness checks.
- Clean-install integration tests use scripted providers; no live company modifications, provider spend or real merges.

## 1.0.0 — 2026-10-05

- Six core foundation seats, six research seats and three context helpers, with optional portfolio COS and generic department blueprints.
- Small core instructions and on-demand process playbooks; company facts and mutable records outside managed files.
- Portable scaffold initialization, generated OpenClaw fragment, conflict-aware preview/apply, reversible backups, rollback and drift report.
- Explicit service contracts and setup paths for an existing Mac house or a fresh Mac/Linux host.
- Fingerprint-based upstream review; no automatic import of company source content or live activation.
