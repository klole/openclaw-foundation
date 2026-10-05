# Runnable service protocol

The Python backend manages durable queues, stages, budgets and receipts. It returns results through workspace files. To request work, write a uniquely named JSON file under work/requests/ and read the same filename under work/results/ after the service polls. Do not edit a submitted request; a response is immutable. Use a new filename for a revision.

Example:

```json
{"action":"work","payload":{"goal":"Reconcile the current goal sheet","maker":"plumber","checker":"push-queue"}}
```

Supported actions: work, research, hire (COS/managers/trainer only), context (payload.goal) and status (payload.job). Bible actions: bible-note (source/as_of/text), bible-read (keeper/control helpers/COS), bible-propose (keeper only, goal/snapshot/facts). Notes start unverified; canonical proposals require a separate reviewer and COS closure. The service can file verified proposals automatically; operator bible-apply is also available. Owner approval is optional installation policy. Control seats do not submit more jobs. Specialists can hand off only to their own declared spawn targets or themselves. Status is visible to the requester and operating control seats. Every public/spend action and every hire still goes through operator authorization. Agents cannot approve, retry uncertain effects, provision, merge or recover backups through this bridge.

A work turn must return the requested JSON schema and actual evidence. Save real deliverables under work/ before referencing them; another seat does not share your filesystem. The backend passes artifacts and their evidence to a fresh independent checker. Native turns use fresh sessions, do not deliver to chat channels, and have bounded time and stage counts. Do not call peers outside the backend review sequence to obtain an approval.

Manager activation additionally requires an evidence-checked research plan and an operator plan approval. Control workers have no independent wake. Specialist wakes stop when the inbox and goal sheet are empty. Treat company-now.md as the freshest collected view, dated snapshot/history as recorded evidence, and conflicts as unresolved.
