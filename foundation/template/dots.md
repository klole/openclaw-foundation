# Connect GPT Dots to OpenClaw

The bridge runs on your existing Mac or Linux host and exposes finite messaging tools over HTTPS. A VPS needs no desktop app. Each person signs in to their own invite-only OAuth identity, sends work to the configured chief of staff and receives signed task-update events. Company facts, credentials and messaging state stay on that installation.

A GitHub link provides software and setup instructions. ChatGPT account sign-in, plugin installation, OAuth consent and the Dot's standing monitoring instruction must be completed for each person. A public repository cannot silently grant access to a private team or install a plugin into someone else's account. Custom MCP/plugin and event permissions must be available in that person's ChatGPT workspace.

## Join an existing team

The operator supplies a private CONNECT.md and that person's PRIVATE-LOGIN file. In ChatGPT Plugins, choose Add custom MCP server, paste the supplied HTTPS /mcp URL, choose OAuth, create the connection and sign in with the private owner name and password. Enable the connection for your Dot. Never paste the connection password into Dot instructions, chat messages or GitHub.

Paste the instruction from CONNECT.md into your Dot. Ask it to discover agents, monitor foundation.task.updated for one conversation, and send a transport-only greeting to the chief of staff. Verify a real reply, a matching event, a nonmatching conversation that produces no event, and Stop monitoring. The software's tests and a delivery receipt alone cannot establish that your Dot received the event.

## Set up a new installation

Install this Foundation release using setup.md, configure the native provider and run its verified worker first. The bridge submits through the existing maker/checker/COS workflow. It never grants permission to approve releases, provision seats or bypass public-action gates.

Use absolute paths. These commands initialize a separate private bridge state folder without starting services:

```sh
python3 /absolute/path/company/foundation dot-init --root /absolute/path/private-dot-state --public-url https://agents.example.com --foundation-root /absolute/path/company --default-agent cos
python3 /absolute/path/company/foundation dot-owner --root /absolute/path/private-dot-state --name owner --agents cos
python3 /absolute/path/company/foundation dot-service-files --root /absolute/path/private-dot-state --python /absolute/path/python3
```

For an existing independently managed OpenClaw, pass --adapter-command-file /private/command.json instead of --foundation-root. This JSON file contains a fixed argv prefix, for example ["/absolute/path/python3", "/private/messaging-client.py"]. The bridge appends exactly foundation_agents, foundation_send or foundation_task_status and passes a JSON object through stdin. The adapter must enforce its identity, agent scope, approval rules and durable idempotency before admitting a model turn. Return a JSON object; send returns task_id (or id) plus status (or state), and status returns the real terminal reply. A new key must never replay an uncertain request. When people share a team, give each owner a separately authenticated adapter command using dot-owner --adapter-command-file. Do not reuse one person's credentials for another.

Keep settings.json, dot.sqlite3, adapter credentials and PRIVATE-LOGIN files outside Git. These files have private modes. dot-owner creates a random password in a private file and emits only its path. Re-running it resets that identity and invalidates its previous OAuth connections. dot-revoke --name OWNER stops future access and delivery for that identity. OAuth refresh tokens rotate; access tokens last an hour and connected authorization lasts up to 30 days before renewed consent. Subscriptions expire within 24 hours unless ChatGPT refreshes them.

Run the bridge under an unprivileged operator service account. Install the generated systemd user unit or launchd plist under your host's normal supervisor, or run dot-serve in an existing supervised process. It includes one bounded background receipt/notification worker. The generated systemd unit uses NoNewPrivileges; use a fixed authenticated messaging adapter rather than requiring the bridge to sudo or opening an administrative shell. An installed Foundation adapter needs access to that company's runtime state, while an SSH adapter can use a forced-command key with messaging access only.

The default HTTP listener binds to 127.0.0.1. Configure a stable TLS reverse proxy from your domain to that listener using the generated Caddyfile example. If your proxy runs inside Docker, use its private host bridge address and set settings.json bind to that exact private address; do not bind the messaging service to a public interface. Preserve existing proxy routes. For a public URL with a path prefix, also route the generated RFC well-known discovery paths to the bridge. Validate and reload the proxy reversibly. No login or message body belongs in access logs.

The default OAuth redirect allowlist contains https://chatgpt.com/connector_platform_oauth_redirect. Issuer identification enables that stable callback. If the ChatGPT connection page shows a different callback, copy that exact HTTPS URI into settings.json redirect_uris and restart the bridge; do not allow arbitrary redirect domains. The built-in authorization server supports public clients with authorization code + S256 PKCE and dynamic registration, not a shared API key. Enterprise verified-domain linking is not implemented because the bridge does not issue OIDC verified-email claims; deployments requiring that protection should integrate an established organization identity provider before use.

## Verification and recovery

Run dot-doctor --root /private/dot-state to inspect owner names, subscription expirations and delivery counts without printing passwords, callback secrets or tokens. Verify GET /health, OAuth discovery, MCP server/discover and tools/list over the public TLS URL. Unauthorized tool calls must receive 401. Owner A must not read owner B's task, and repeating exactly the same send must return the original task. Restarts must preserve receipts and subscriptions. Revoke an owner and verify both calls and notifications stop.

MCP Events uses 2026-07-28 discovery, authenticated subscriptions, callback challenge verification and Standard Webhooks HMAC signatures. Callback connections resolve and pin public addresses, verify TLS using the original hostname and never follow redirects. Notifications contain only task IDs, conversation and status; authenticated read tools retrieve replies. Delivery retries retain the same event ID. Clients must deduplicate and must not treat notification text as permission for new work. This event type has no protocol replay; foundation_conversation recovers missed status updates.

For updates, stop the bridge and its worker, save settings, adapter credentials and a consistent private copy of dot.sqlite3, then preview/apply the new Foundation version and restart. Keep private login files local. A standalone source deployment should use immutable release directories and switch the supervised code path only after tests and review. Rollback switches code back and restores a compatible private state snapshot. Never replace a published release asset under the same version. Foundation's daily release checker prompts for reviewed updates; it does not rewrite a running bridge or rotate access automatically.

Public sharing is a preview until independent review. A deployed server and successful local protocol tests are separate from a live Dot proof. Do not describe the setup as fully verified until the account connection, subscription and actual returned reply have been observed in ChatGPT.

Official references: [MCP Events](https://developers.openai.com/plugins/build/mcp-events), [OAuth](https://developers.openai.com/plugins/build/auth), [MCP deployment](https://developers.openai.com/plugins/build/mcp-server), [plugin installation and sharing](https://developers.openai.com/plugins/build/plugins).
