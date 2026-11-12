       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTMNT.
       AUTHOR. LPW.
      *****************************************************************
      * ACCTMNT  - ACCOUNT MAINTENANCE (ON REQUEST, NOT NIGHTLY)
      *            READS MNTREQ.DAT, UPDATES ACCOUNT MASTER
      *
      * CHANGE LOG
      * 1992-06 LPW INITIAL VERSION - OPEN/CLOSE ONLY
      * 1994-09 LPW ADD FREEZE / UNFREEZE
      * 1998-11 RJT Y2K REMEDIATION - OPEN DATE FROM REQUEST IS YYDDD
      * 2002-04 LPW ADD RATE CHANGE (RC)
      * 2010-08 TGB REJECT CLOSE IF BALANCE NOT ZERO
      *****************************************************************
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCT-IN ASSIGN TO ACCTIN
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-AIN.
           SELECT ACCT-OUT ASSIGN TO ACCTOUT
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-AOUT.
           SELECT MNT-FILE ASSIGN TO MNTREQ
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-MNT.
       DATA DIVISION.
       FILE SECTION.
       FD  ACCT-IN.
       01  ACCT-IN-REC                 PIC X(100).
       FD  ACCT-OUT.
       01  ACCT-OUT-REC                PIC X(100).
       FD  MNT-FILE.
       01  MNT-REC.
           05  MNT-ACCT                PIC 9(10).
           05  MNT-ACTION              PIC X(2).
               88  MNT-OPEN            VALUE 'OP'.
               88  MNT-CLOSE           VALUE 'CL'.
               88  MNT-FREEZE          VALUE 'FZ'.
               88  MNT-UNFREEZE        VALUE 'UF'.
               88  MNT-RATE            VALUE 'RC'.
           05  MNT-PRODUCT             PIC X(3).
           05  MNT-NAME                PIC X(30).
           05  MNT-RATE-NEW            PIC 9V9(5).
           05  MNT-DATE                PIC 9(5).
           05  FILLER                  PIC X(24).
       WORKING-STORAGE SECTION.
           COPY ACCTREC.
       01  WS-FS-AIN                   PIC XX.
       01  WS-FS-AOUT                  PIC XX.
       01  WS-FS-MNT                   PIC XX.
       01  WS-SWITCHES.
           05  WS-MEOF-SW              PIC X VALUE 'N'.
               88  MNT-EOF             VALUE 'Y'.
           05  WS-AEOF-SW              PIC X VALUE 'N'.
               88  AIN-EOF             VALUE 'Y'.
           05  WS-FOUND-SW             PIC X.
               88  ACCT-FOUND          VALUE 'Y'.
       01  WS-ACCT-CNT                 PIC 9(4) COMP VALUE ZERO.
       01  WS-IX                       PIC 9(4) COMP.
       01  WS-JX                       PIC 9(4) COMP.
       01  WS-ACCT-TBL.
           05  WS-TE OCCURS 500 TIMES.
               10  WS-TE-KEY           PIC 9(10).
               10  WS-TE-REST          PIC X(90).
       01  WS-CNT-APPLIED              PIC 9(5) VALUE ZERO.
       01  WS-CNT-REJECTED             PIC 9(5) VALUE ZERO.
       01  WS-OPERATOR-ID              PIC X(8) VALUE SPACES.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT
           PERFORM 2000-PROCESS-REQUEST UNTIL MNT-EOF
           PERFORM 8000-REWRITE-MASTER
           PERFORM 9000-TERM
           STOP RUN.
       1000-INIT.
           OPEN INPUT ACCT-IN MNT-FILE
           IF WS-FS-AIN NOT = '00' OR WS-FS-MNT NOT = '00'
               DISPLAY 'ACCTMNT OPEN ERROR ' WS-FS-AIN WS-FS-MNT
               PERFORM 9900-ABEND
           END-IF
           PERFORM UNTIL AIN-EOF
               READ ACCT-IN
                   AT END
                       SET AIN-EOF TO TRUE
                   NOT AT END
                       ADD 1 TO WS-ACCT-CNT
                       MOVE ACCT-IN-REC TO WS-TE(WS-ACCT-CNT)
               END-READ
           END-PERFORM
           CLOSE ACCT-IN
           PERFORM 1200-READ-REQUEST.
       1200-READ-REQUEST.
           READ MNT-FILE
               AT END
                   SET MNT-EOF TO TRUE
           END-READ.
       2000-PROCESS-REQUEST.
           PERFORM 2050-FIND-ACCT
           EVALUATE TRUE
               WHEN MNT-OPEN
                   PERFORM 2100-OPEN-ACCOUNT
               WHEN MNT-CLOSE
                   PERFORM 2200-CLOSE-ACCOUNT
               WHEN MNT-FREEZE
                   PERFORM 2300-FREEZE-ACCOUNT
               WHEN MNT-UNFREEZE
                   PERFORM 2400-UNFREEZE-ACCOUNT
               WHEN MNT-RATE
                   PERFORM 2500-CHANGE-RATE
               WHEN OTHER
                   DISPLAY 'ACCTMNT BAD ACTION ' MNT-ACTION
                   ADD 1 TO WS-CNT-REJECTED
           END-EVALUATE
           PERFORM 1200-READ-REQUEST.
       2050-FIND-ACCT.
           MOVE 'N' TO WS-FOUND-SW
           PERFORM VARYING WS-IX FROM 1 BY 1
               UNTIL WS-IX > WS-ACCT-CNT OR ACCT-FOUND
               IF WS-TE-KEY(WS-IX) = MNT-ACCT
                   MOVE 'Y' TO WS-FOUND-SW
                   MOVE WS-TE(WS-IX) TO ACCT-REC
               END-IF
           END-PERFORM
           IF ACCT-FOUND
               SUBTRACT 1 FROM WS-IX
           END-IF.
       2100-OPEN-ACCOUNT.
           IF ACCT-FOUND OR WS-ACCT-CNT >= 500
               DISPLAY 'ACCTMNT OPEN REJECTED ' MNT-ACCT
               ADD 1 TO WS-CNT-REJECTED
           ELSE
               MOVE SPACES TO ACCT-REC
               MOVE MNT-ACCT TO ACCT-NUMBER
               MOVE MNT-PRODUCT TO ACCT-PRODUCT
               MOVE 'A' TO ACCT-STATUS
               MOVE MNT-DATE TO ACCT-OPEN-DATE
               MOVE MNT-NAME TO ACCT-CUST-NAME
               MOVE ZERO TO ACCT-BALANCE ACCT-ACCRUED-INT
               MOVE MNT-RATE-NEW TO ACCT-RATE
               MOVE MNT-DATE TO ACCT-LAST-ACT-DATE
               MOVE ZERO TO ACCT-OD-COUNT
               PERFORM 2150-INSERT-SORTED
               ADD 1 TO WS-CNT-APPLIED
           END-IF.
       2150-INSERT-SORTED.
           MOVE 1 TO WS-IX
           PERFORM UNTIL WS-IX > WS-ACCT-CNT
                      OR WS-TE-KEY(WS-IX) > ACCT-NUMBER
               ADD 1 TO WS-IX
           END-PERFORM
           PERFORM VARYING WS-JX FROM WS-ACCT-CNT BY -1
               UNTIL WS-JX < WS-IX
               MOVE WS-TE(WS-JX) TO WS-TE(WS-JX + 1)
           END-PERFORM
           MOVE ACCT-REC TO WS-TE(WS-IX)
           ADD 1 TO WS-ACCT-CNT.
       2200-CLOSE-ACCOUNT.
           IF NOT ACCT-FOUND OR ACCT-BALANCE NOT = 0
               DISPLAY 'ACCTMNT CLOSE REJECTED ' MNT-ACCT
               ADD 1 TO WS-CNT-REJECTED
           ELSE
               MOVE 'C' TO ACCT-STATUS
               MOVE MNT-DATE TO ACCT-LAST-ACT-DATE
               MOVE ACCT-REC TO WS-TE(WS-IX)
               ADD 1 TO WS-CNT-APPLIED
           END-IF.
       2300-FREEZE-ACCOUNT.
           IF NOT ACCT-FOUND OR ACCT-CLOSED
               ADD 1 TO WS-CNT-REJECTED
           ELSE
               MOVE 'F' TO ACCT-STATUS
               MOVE ACCT-REC TO WS-TE(WS-IX)
               ADD 1 TO WS-CNT-APPLIED
           END-IF.
       2400-UNFREEZE-ACCOUNT.
           IF NOT ACCT-FOUND OR NOT ACCT-FROZEN
               ADD 1 TO WS-CNT-REJECTED
           ELSE
               MOVE 'A' TO ACCT-STATUS
               MOVE ACCT-REC TO WS-TE(WS-IX)
               ADD 1 TO WS-CNT-APPLIED
           END-IF.
       2500-CHANGE-RATE.
           IF NOT ACCT-FOUND OR ACCT-CLOSED
               ADD 1 TO WS-CNT-REJECTED
           ELSE
               MOVE MNT-RATE-NEW TO ACCT-RATE
               MOVE ACCT-REC TO WS-TE(WS-IX)
               ADD 1 TO WS-CNT-APPLIED
           END-IF.
       8000-REWRITE-MASTER.
           OPEN OUTPUT ACCT-OUT
           IF WS-FS-AOUT NOT = '00'
               DISPLAY 'ACCTMNT OPEN ACCTOUT FS=' WS-FS-AOUT
               PERFORM 9900-ABEND
           END-IF
           PERFORM VARYING WS-IX FROM 1 BY 1
               UNTIL WS-IX > WS-ACCT-CNT
               WRITE ACCT-OUT-REC FROM WS-TE(WS-IX)
           END-PERFORM
           CLOSE ACCT-OUT.
       9000-TERM.
           CLOSE MNT-FILE
           DISPLAY 'ACCTMNT APPLIED  ' WS-CNT-APPLIED
           DISPLAY 'ACCTMNT REJECTED ' WS-CNT-REJECTED.
       9900-ABEND.
           MOVE 16 TO RETURN-CODE
           STOP RUN.
