# Project LIGHTHOUSE

Harbor Point Savings & Trust: replacement of the nightly COBOL core-banking batch with a Java 21 / Spring Boot 3 system.

- `legacy/` COBOL source, JCL, ops README, captured production inputs (`data/input/`) and outputs (`data/golden/`).
- `modern/` the new system (Maven wrapper; `./mvnw -q -B verify`).
- `team/` ticket board and standups. `docs/` ADRs, legacy specs, handoffs, runbook, releases.

Go-live criterion: golden-master parity for 2025-02-01..2025-03-31, except deviations approved in writing by the business.
