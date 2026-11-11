# LH-1 LIGHTHOUSE: replace the nightly COBOL batch

Status: In progress
Owner: Priya Okonkwo
Created: 2025-02-03

## Description
Reimplement the NIGHTLY batch (XFERPROC, INTCALC, EODPOST, FEEASSES, STMTGEN) and ACCTMNT in Java 21 / Spring Boot 3, migrate the
account master, and prove golden-master parity on the captured February-March 2025 production run.

## Acceptance criteria
- Every business day 2025-02-01..2025-03-31 reproduces POSTED, REJECTS and ACCTMAST exactly; month-end statements match.
- Any deviation from legacy behaviour is approved in writing by the business.
- Compliance requirements are met; CI is green.

## Notes
- 2025-02-03 Kickoff. The PO creates the backlog in sprint 1.
