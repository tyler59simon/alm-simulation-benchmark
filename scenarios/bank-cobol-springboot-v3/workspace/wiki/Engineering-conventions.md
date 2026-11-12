# Engineering conventions

## Commits
- **Policy ENG-7:** the first line of every commit message starts with its tracker key: `LH-123: Add daily accrual job`.
  A git hook installed on every workstation rejects anything else.
- Work on your own branch; never push. Release engineering merges every branch into `main` at the end of each working session wave and runs CI.

## CI (runs on `main` after each merge)
1. `mvnw -B verify` in `modern/`.
2. **ci-lint** (company rules, run by the CI server only):
   - **L1:** no `System.out` / `System.err` printing in production code (`src/main`); use the logger.
   - **L2:** every `TODO` or `FIXME` names its ticket: `// TODO(LH-123): ...`.
   You can run the same lint locally: `py "{{WORKSPACE}}/bin/lint.py" <path to the repo>`.

## Tracker
Tickets live in the tracker (`{{WORKSPACE}}/tracker`). Create them with `py "{{WORKSPACE}}/bin/tracker.py" new "Title" --owner "Name"`
so keys are unique; then edit the file (Status, Owner, Description, Acceptance criteria, dated Notes).

## Decisions
Business decisions are only real once written down: the PO records them; architecture decisions go in `docs/adr/` in the repo.
