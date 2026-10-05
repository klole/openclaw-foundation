# Independent change review

Maker supplies exact changed files, goal, evidence, before/after tests, risk and rollback. Reviewer checks correctness, accidental overwrites/deletions/downgrades, public impact, authority and concurrent contributions. Verdict: PASS, FIX or HUMAN REVIEW. Keep the reviewer separate from the maker; independent verification needs fresh inputs.

Merge Gate applies repository checks and the configured approval rules. Release Gate challenges agent roles, held-out cases and consequential plans. Judge provides bounded evidence decisions; it cannot grant spending, public-release or owner authority. The producer never merges its own change. Record the released version and verify actual post-release behavior before closing the task.
