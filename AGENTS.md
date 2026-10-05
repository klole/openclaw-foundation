# Working on OpenClaw Foundation

Use an isolated worktree/checkout and a codex/ branch for each task. Preserve other contributors' work. Open a pull request; authors must not merge their own PRs. Require passing CI and independent review before merging.

This repository is a company-neutral distribution. Do not copy installed company directories, credentials, auth state, sessions, business records, real metrics, private origin repositories or their history into it. Use synthetic fixtures in tests.

Run `python3 -m unittest discover -s foundation/tests -v` for runtime/updater changes and `python3 tools/build_distribution.py --output <fresh-output-directory>` before publishing. Python 3.9+ and the standard library are supported.

Update foundation/foundation.py VERSION and the matching CHANGELOG heading for releases. Published version assets are immutable. Prepare releases from reviewed main; publish candidates as prereleases. The release workflow creates a draft for the maintainer to inspect and publish.

Daily release checks and downloads must never apply executable changes, send company context to GitHub, restart gateways or grant agent permissions. Installation uses explicit operator preview/apply/rollback. Preserve local company data and custom agents; managed drift blocks updates. Test failure modes, integrity and privacy boundaries.
