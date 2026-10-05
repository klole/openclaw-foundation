# Proactivity, monitoring and wakes

Use deterministic collection and change detection before invoking an agent. Manager behavior is proactive; specialist behavior is request-driven; workers wake only through their parent. The scheduler's adaptive ladder supports URGENT 5m, INTENSE 15m, BUILDING 30m, PREPARING 1h, STEADY 3h, QUIET 6h, DORMANT 12h, plus OFF for idle specialists. Configure cost, action and concurrency caps before enabling the ladder.

The monitor reads tasks, approvals, builds, tool/model failures, research health and limits. New/reopened/escalated incidents get an owner and next action; unchanged incidents are deduplicated. Unreadable sources never clear prior incidents. Recovery requires a successful fresh readback. Budget counters resetting are not repairs.

Stall checks recheck the blocker, seek an alternate authorized path and route the repair in the same turn. Each recurring job needs its source, timezone, trigger/interval, output owner, permitted actions, max actions/cost/runtime, overlap lock, retry/backoff, deduplication key and stop conditions. Stay quiet when nothing meaningful changed. Native heartbeats are OFF in the generated fragment while the portable scheduler owns wakes; use one scheduling owner to prevent double wakes.
