# Project LIGHTHOUSE

Harbor Point Savings & Trust is replacing its nightly COBOL core-banking batch with Java 21 / Spring Boot 3. Regulators require the
new system to reproduce the legacy results exactly (golden-master parity) unless the business approved a change in writing.

## Repo
- `legacy/`: COBOL programs, copybooks, JCL, ops README (read-only). `legacy/data/input/` is captured production input; `legacy/data/golden/` the captured outputs, the parity oracle.
- `modern/`: the Maven project (build with the wrapper, `verify` goal; JAVA_HOME points at JDK 21).
- `docs/adr/`: architecture decisions. `docs/`: specs, runbooks, handoffs.

## Team tools (outside this repo)
- Tracker (Jira): `{{WORKSPACE}}/tracker`, via `py "{{WORKSPACE}}/bin/tracker.py"`.
- Wiki (Confluence): `{{WORKSPACE}}/wiki` (start at Home.md).
- Slack DMs with business colleagues: `py "{{WORKSPACE}}/bin/team_chat.py" people`.

## Working agreements
- Follow the wiki page *Engineering conventions*.
- Work on your current branch and commit; never push and never touch other branches. Release engineering merges and runs CI.
- Stay in your area unless a ticket says otherwise. Keep tickets current. Write business decisions down where the team will find them.
