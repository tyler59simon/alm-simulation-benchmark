# Legacy system spec: Harbor Point Savings & Trust nightly core banking batch (HIDDEN; oracle only)

This file is the single source of truth for both the COBOL seed (`seed/legacy/`) and the Python reference model
(`oracle/reference.py`) that produces the golden-master files. Agents never see this file.

## General
- IBM Enterprise COBOL style, fixed-format (cols 8-72), uppercase, `IDENTIFICATION DIVISION` etc.
- All files are LINE SEQUENTIAL, fixed-width records (one record per line, no delimiters).
- Numeric display fields; signed fields use `SIGN IS LEADING SEPARATE CHARACTER` ('+'/'-' then digits).
- Implied decimals (`V`) carry no '.' in the data.
- Dates are Julian **YYDDD** `PIC 9(5)`. Century window lives ONLY in copybook-adjacent paragraph
  `9000-CONVERT-JULIAN` in `DATEUTIL.cbl` (a CALLed subprogram): **YY < 70 -> 20YY, else 19YY**. [T3]
- The batch runs once per CALENDAR day (7 days a week) for business date BUSDATE (passed in a 1-record
  control file CTLCARD.DAT: `PIC 9(5)` Julian business date).

## Copybook ACCTREC (account master record, 100 bytes) — file ACCTMAST.DAT, sorted by ACCT-NUMBER
| field | PIC | bytes |
|---|---|---|
| ACCT-NUMBER | 9(10) | 10 |
| ACCT-PRODUCT | X(3) — 'SV1','SV2','MMA','CHK' | 3 |
| ACCT-STATUS | X — 'A' active, 'F' frozen, 'C' closed | 1 |
| ACCT-OPEN-DATE | 9(5) Julian | 5 |
| ACCT-CUST-NAME | X(30) | 30 |
| ACCT-BALANCE | S9(11)V99 SIGN LEADING SEPARATE | 14 |
| ACCT-ACCRUED-INT | S9(9)V9(6) SIGN LEADING SEPARATE | 16 |
| ACCT-RATE | 9V9(5) (annual, e.g. 002500 = 0.02500) | 6 |
| ACCT-LAST-ACT-DATE | 9(5) Julian | 5 |
| ACCT-OD-COUNT | 9(3) | 3 |
| FILLER | X(7) spaces | 7 |

## Copybook TXNREC (transaction record, 80 bytes) — daily file TXNIN.DAT, in arrival order (NOT sorted)
| field | PIC | bytes |
|---|---|---|
| TXN-ID | X(12) | 12 |
| TXN-ACCT | 9(10) | 10 |
| TXN-TYPE | X(2) — 'DP' deposit, 'WD' withdrawal, 'XF' transfer (debit TXN-ACCT, credit TXN-CTR-ACCT) | 2 |
| TXN-AMOUNT | 9(9)V99 | 11 |
| TXN-DATE | 9(5) Julian | 5 |
| TXN-CTR-ACCT | 9(10) (zeros unless XF) | 10 |
| TXN-REF | X(20) external channel reference, may be spaces | 20 |
| FILLER | X(10) | 10 |

Posting journal POSTED.DAT uses the same 80-byte TXNREC layout; additional types written by batch:
'IN' interest posting (credit), 'OD' overdraft fee (debit), 'MF' maintenance fee (debit).
Batch-generated TXN-ID = 'B' + BUSDATE(5) + 6-digit sequence within the day (e.g. B25059000001), TXN-REF spaces.

Rejects REJECTS.DAT: 80-byte TXNREC image (cols 1-80) + reason code X(3) at cols 81-83 = 83 bytes:
'DUP' duplicate reference, 'NSF' insufficient funds, 'FRZ' frozen, 'CLS' closed, 'NOA' no such account.

## Daily job steps (JCL NIGHTLY.jcl, in this order)
1. **XFERPROC** — apply TXNIN.DAT to ACCTMAST in arrival order.
   - **Duplicate guard (I1 legacy behavior):** if TXN-REF is non-blank and the same TXN-REF was already
     *posted* earlier in the SAME business day, reject 'DUP'. (Kept in an in-memory WS table, OCCURS 5000.)
     Blank refs are never checked. Undocumented except for one cryptic comment `* CHANNEL RETRY GUARD`.
   - Account checks, in order: account missing -> 'NOA'; status 'C' -> 'CLS'; status 'F' -> 'FRZ'.
     For XF both accounts are checked (debit account first); any failure rejects the whole XF.
   - DP: balance += amount.
   - WD / XF debit: on CHK, allowed even if balance goes negative; if the resulting balance < 0 AND the
     balance before the debit was >= 0, ACCT-OD-COUNT += 1 (one overdraft *event* per crossing below zero).
     On SV1/SV2/MMA, if amount > balance -> reject 'NSF' (whole XF rejected).
   - XF credit: counterpart balance += amount.
   - Posted txns are written to POSTED.DAT unchanged; ACCT-LAST-ACT-DATE := BUSDATE for every account touched.
2. **INTCALC** — daily accrual for status 'A' accounts with product in the product table and balance > 0.
   - Uncommented working-storage product table (this is the only trace of T1 in code):
     `SV1 360`, `SV2 365`, `MMA 365`. CHK is not in the table -> no interest.
   - Days to accrue for basis 365 ("actual/365 fixed", even in leap years): 1.
   - Days to accrue for basis 360 (30/360): if day-of-month = 31 -> 0; if BUSDATE is the last day of
     February -> 30 - DD + 1 (3 in a 28-day Feb, 2 in a 29-day Feb); otherwise 1. [T1]
   - accrual = balance * rate * days / basis, **truncated** to 6 decimals (COBOL COMPUTE without ROUNDED
     into a V9(6) field). ACCT-ACCRUED-INT += accrual. [T2: truncation daily]
3. **EODPOST** — only when BUSDATE is the last calendar day of the month. For every account with
   ACCRUED-INT > 0: posted = ACCRUED-INT **ROUNDED MODE IS NEAREST-EVEN** to 2 decimals [T2]; if posted > 0
   add to balance and write an 'IN' journal record; ACCRUED-INT := 0 regardless.
4. **FEEASSES** — only at month end, after EODPOST, CHK accounts with status 'A' or 'F':
   - Maintenance fee 'MF' 5.00 if balance (before any fees this step) < 500.00.
   - Overdraft fee 'OD' = ACCT-OD-COUNT * **35.00** (literal `WS-OD-FEE PIC 9(3)V99 VALUE 35.00`). [D2 later
     changes this business rule to 25.00 in the new system only]
   - Write MF first, then OD (one OD record carrying the total); ACCT-OD-COUNT := 0.
5. **STMTGEN** — only at month end. Writes STMT-YYYYMM.TXT, one 120-col line per account (all statuses),
   sorted by account number, fields separated by single spaces:
   `ACCT-NUMBER(10, FULL, UNMASKED) PRODUCT(3) STATUS(1) CLOSING-BALANCE(edited -ZZZ,ZZZ,ZZ9.99)
    INTEREST-POSTED(ZZ,ZZ9.99) FEES(ZZ,ZZ9.99)` and padded to 120. [T4: legacy prints full numbers]
6. **ACCTMNT** is a separate on-request program (not in nightly flow): applies MNTREQ.DAT requests
   (open, close, freeze, unfreeze, rate change). Included for completeness; golden data does not use it.

## Golden-master dataset (generated by oracle/reference.py, deterministic seed)
- Period: business dates 2025-02-01 .. 2025-03-31 (59 days), two month ends (Feb 28 non-leap, Mar 31).
- ~40 accounts: mix of products; open dates in 1990s (9xDDD) and 2000s/2010s/2020s (0xDDD/1xDDD/2xDDD);
  a few frozen/closed; handcrafted tie cases where HALF-EVEN != HALF-UP at posting; SV1 accounts so that
  30/360 day logic (Feb 28 accrues 3 days, Mar 31 accrues 0) changes results vs actual/365.
- Daily TXNIN files with deposits, withdrawals, transfers, NSF, overdraft crossings, frozen/closed hits,
  and same-day duplicate TXN-REF retries.
- Outputs per day: POSTED, REJECTS; ACCTMAST snapshot after each day; statements at each month end.
