# Update, rollback and recovery

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
