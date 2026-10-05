# Update, rollback and recovery

## Daily GitHub updates

The foundation checks `klole/openclaw-foundation` releases once every 24 hours while `serve` runs. It sends only GitHub metadata/download requests; no company context or usage records leave the installation. A newer release adds one COS inbox notice and an update panel in the local HQ. The COS tells its owner; the owner fetches, previews and approves installation. No external email/chat integration is assumed. A checker alone does not activate the worker or send an external notification.

The default `updates` settings in config/backend.json are:

```json
{"enabled": true, "repository": "klole/openclaw-foundation", "channel": "stable", "interval_seconds": 86400, "token_env": ""}
```

`stable` ignores prereleases and drafts. `preview` includes published prereleases for test installations. During the initial candidate period there is no stable release: stable copies simply report no available release. Change the channel to preview to try 2.1.0-rc.1. Setting enabled=false stops network checks. Existing config files receive these defaults at runtime without being overwritten. Checks target the highest packaged semantic version among the 100 most recent releases; unpublished tags and unfinished PRs are ignored. GitHub outages retain the last known notice, wait until the next daily attempt, and do not stop company work. `--force` retries immediately.

```sh
python3 /absolute/path/company/foundation check-updates --force
python3 /absolute/path/company/foundation fetch-update --version 2.1.0-rc.1
```

Fetch downloads only a published release on the configured channel, verifies SHA256SUMS, a GitHub asset digest when available, archive checksums and its exact version, then caches it privately in state/updates/downloads. It prints the exact preview and apply commands. It never installs code. Review release notes and stop the worker before preview/apply; save a private application backup. The ordinary `update --bundle ... --apply` command is the explicit owner approval. After applying, use migrate, provision preview/apply, restart the gateway, verify seats and restart the worker as described below. The template updater updates the foundation; upgrades to the OpenClaw executable use that project's normal update process.

Checksums detect alteration relative to the GitHub release, and HTTPS/account access establishes the source. They are not an independent publisher signature. Trust repository write access; require reviewed changes and protect maintainer accounts. Downloads refuse arbitrary URLs and drop authorization on cross-host GitHub redirects. For a private repository, set token_env to the name of a local environment variable containing a fine-grained GitHub token with repository Contents read access. Never put the token itself in backend.json; the host supervisor must provide that environment variable. Public installs need no token.

## Run the checker while the worker is stopped

`serve` already performs daily checks. For installations that stop the worker regularly, generate a separate host checker:

```sh
python3 /absolute/path/company/foundation update-service-files
```

This writes scheduler files and reports their paths; it does not activate them. Pick one option for the installation. Both schedulers and the worker share a lock and persisted check time, so they do not duplicate notices.

On macOS, copy the reported org.openclaw.foundation-updates.COMPANY-ID.plist to ~/Library/LaunchAgents, then load that exact plist with `launchctl bootstrap gui/$(id -u) <absolute-plist-path>`. It runs at load and every 24 hours while that user's host session is active. `launchctl bootout gui/$(id -u) <absolute-plist-path>` disables it. Do not share plist files between company roots.

On Linux, copy the reported service and timer to ~/.config/systemd/user, run `systemctl --user daemon-reload`, then `systemctl --user enable --now foundation-update-check.timer`. Disable with `systemctl --user disable --now foundation-update-check.timer`. A logged-out user needs systemd user lingering configured by the host operator. For multiple companies in one OS account, rename the service/timer to a unique pair and add `Unit=<unique-service-name>.service` to each timer's [Timer] section. Inspect service paths before activation.

## Publishing improvements

Make each improvement on a codex/ branch, open a PR, pass CI and obtain independent review. Change VERSION in foundation/foundation.py and add the exact version to foundation/CHANGELOG.md before a release. Use a prerelease suffix while testing. After the PR is merged, run GitHub Actions → Prepare release on main. It tests, packages the neutral source, and creates a draft release with an executable ZIP and SHA256SUMS. Review and publish the draft when ready. Each installation detects that published release within a day. Frequent merges do not require a release for every commit; publish when an improvement is ready to distribute. Never replace an existing published version's assets.


## Updating one or many copies

Maintain one neutral source and distribute one immutable archive/version/checksum. Apply it independently to each configured root on either host. Roots retain their own config, company context, Bible, custom agents, work, memory, queues, approvals, incidents and budgets. Never distribute an installed company directory as a template.

Stop the persistent foundation worker first; template operations refuse a running service or active lease. Back up the installation outside its root. For example:

```sh
python3 /absolute/path/company/foundation backup --output /absolute/path/private-backups/company-before-upgrade.zip
python3 /absolute/path/company/foundation update --bundle /absolute/path/openclaw-foundation-2.1.0.zip
python3 /absolute/path/company/foundation update --bundle /absolute/path/openclaw-foundation-2.1.0.zip --apply
python3 /absolute/path/company/foundation migrate --apply
python3 /absolute/path/company/foundation provision
python3 /absolute/path/company/foundation provision --apply
python3 /absolute/path/company/foundation doctor
```

Preview is read-only. Apply validates the archive, blocks drift, saves before/after hashes and original managed bytes, and restores its own changes on a write failure. An OS crash can leave a partial transaction: inspect `.foundation/backups/<id>/transaction.json` and recover its originals before another update. This is not a single atomic transaction spanning native gateway and application data.

Runtime migrations are explicit, additive and fail closed on an unsupported newer schema. The included schema 1 → 2 migration retains jobs, approvals, usage and incidents and adds receipts/attempt fields. Rollback of managed code does not erase application history or reverse a schema migration. Restore a pre-upgrade application backup into a fresh root if a future incompatible migration requires data recovery.

Native provisioning validates a private candidate through the target OpenClaw schema, refuses changed tracked entries, and records a separate receipt. Restart the dedicated gateway after native changes, rerun fresh seat proofs, then restart the worker. Existing model sessions or daemon imports can retain old instructions/code until restart. Reapply each copy independently; partial fleet updates leave unchanged roots on their previous version.

A v1 scaffold can accept the v2 archive using its installed updater. The next invocation uses the new backend. An absent backend config uses conservative defaults; copy backend.example.json to config/backend.json before enabling native calls. v1 legacy services.json is retained as historical operator data and is no longer the engine configuration.

## Local customization

Edit config/company.json, config/backend.json, company/RULES.md, bible/SNAPSHOT.md and custom/ sources. `render` previews and `render --apply` rebuilds instructions/roster/native fragment. Current collected context is mutable company data and is not overwritten by render. Playbooks and bootstrap instructions are generated: do not edit them in place. Move intended role changes into custom/roles/<id>.md; restore a drifted managed file from its known installed release before updating. There is no force-overwrite switch. Review future upstream role changes against local overrides.

## Rollback

```sh
python3 /absolute/path/company/foundation rollback
python3 /absolute/path/company/foundation rollback --apply
python3 /absolute/path/company/foundation provision-rollback --receipt <provision-receipt>
python3 /absolute/path/company/foundation provision-rollback --receipt <provision-receipt> --apply
```

Managed rollback defaults to the latest transaction or accepts `--backup <id>`. It verifies source bytes and refuses subsequent drift. Native rollback restores the exact prior config only if its post-provision checksum still matches. Restart the gateway afterwards. These are separate operations; reconcile external edits rather than overwriting them. Backups of generated instructions and native candidates are private company records.

## Application recovery and native state

`backup` saves installation code, company/Bible/custom sources, runtime jobs and receipts, workspaces, memory and archives. It uses SQLite's snapshot API for database files. Secrets, native candidate backups, auth, environment files, locks and previous backups are excluded. Stop workers and finish/inspect leases first. Store the checksummed, mode-0600 archive privately outside the installation.

`restore --archive <backup.zip> --destination <fresh-root>` previews; add `--apply` to restore. It rejects unsafe paths, changed checksums and an existing destination. Restored native transport and wakes are disabled. Run render to rebind workspace paths, review target native config/state, provision, restart and prove seats before resuming. Recovery preserves current evidence by restoring into a fresh directory.

The application backup is not an entire host image. Back up the dedicated OpenClaw config/state, sessions, provider credentials and credential broker using your normal private host backup procedure too. See operations.md for `backup --native` and `restore-native`, which can include that dedicated profile in a private recovery archive. Credentials belong only to recovery of that company, never a new-company template.

## Maintaining the neutral source

Work in an isolated branch, port only company-neutral mechanics, update CHANGELOG, run the full checks and open a pull request for independent review. Publish each tested archive under a new version. Release checksums detect corruption and depend on trust in the GitHub publisher. Never distribute installed company directories or credentials.

```sh
python3 foundation/foundation.py release --version 2.1.0 --output /absolute/path/openclaw-foundation-2.1.0.zip
```
