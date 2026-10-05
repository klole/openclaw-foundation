# Set up company truth and historical memory

1. Owner supplies company identity, exact goals/targets, customers, operations, terminology and standing rules. Put universal facts in bible/SNAPSHOT.md and detail in topic files. Empty areas stay unknown.
2. Inventory authoritative sources, owner, scope, credentials broker reference, metric definitions, timezone, source coverage and freshness. Read-only sources first. Do not put credentials or customer records in files.
3. Configure the built-in context collector with company/context/sources.json, for example `{"sources":[{"id":"approved-export","type":"json-file","path":"company/context/approved-export.json","owner":"librarian"}]}`. The referenced file must be a `{"facts": [...]}` typed export. Run `foundation collect`. Each current fact has id, area, label, value, as_of, source, fresh_hours and optional note/recorded_by. Exactly one value per fact id. Areas: company, numbers, offers, marketing, tools, people, gaps. Adapt domain-specific areas deliberately.
4. Collected values win for observed state; owner decisions represent approved intent. Disagreements are conflicts, not silent overrides. Missing or failed sources carry the last known value as stale or show unknown. Old values and why they changed go to Bible history and decisions.
5. Keeper briefs the metrics worker and current-state worker as needed. Recorder summarizes a supplied verified change packet. The keeper independently checks and files notes.
6. Context packets fit the goal: headline facts and metrics with periods/coverage, applicable rules and decisions, relevant current state, open conflicts, stale facts and gaps with owners. Freeze the packet for builds and research.
7. Test fictional fact changes, failed sources, stale metrics, conflicts and packet relevance before enabling collection. Verify no customer personal data or credentials enter output.

Suggested company layout: company/context/{facts.json,sources.json,current.json,INDEX.md,conflicts.md,CHANGES.json}; bible/{SNAPSHOT.md,decisions.md,history.md,CONFLICTS.md,inbox/,topic files}. Source records and Bible files belong to the installation and are never updated from a template release.
