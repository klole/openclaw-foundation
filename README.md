# OpenClaw Foundation

A reusable company-neutral foundation for OpenClaw on macOS and Linux. It includes COS and operating agents, department blueprints, context and Bible instructions, bounded workflows, a local HQ, and preview/apply/rollback updates. Each company supplies its own facts, credentials and provider connections.

Download a packaged ZIP and SHA256SUMS from [Releases](https://github.com/klole/openclaw-foundation/releases), fill [company.example.json](foundation/template/company.example.json), then create a fresh company directory:

```sh
python3 openclaw-foundation-2.1.0-rc.1.zip init --config /absolute/path/company.json --root /absolute/path/new-company
python3 /absolute/path/new-company/foundation doctor
```

Python 3.9+; standard library only. Follow [setup](foundation/template/setup.md), [operations](foundation/template/operations.md), and [updates](foundation/template/updates.md). Initialization starts no model calls and modifies no live gateway.

Daily checks detect new GitHub releases, show what changed in HQ, and notify the local COS. The owner approves installation using the existing preview/apply/rollback workflow. Stable copies ignore preview candidates. Early releases are candidates awaiting independent review; choose the preview channel to test them. The foundation updater updates this template's code and instructions; OpenClaw executable upgrades remain separate.

For maintainers: work on an isolated codex/ branch, open a PR and obtain independent review. Bump the version and changelog, then run the Prepare release workflow on main after merging. It creates a draft; publish it when ready. See [publishing instructions](foundation/template/updates.md#publishing-improvements).

```sh
python3 -m unittest discover -s foundation/tests -v
python3 tools/build_distribution.py --output dist
```

This repository contains clean template history only. Installed company directories, credentials, memory and private backups belong outside it. Release checks send no company context to GitHub.
