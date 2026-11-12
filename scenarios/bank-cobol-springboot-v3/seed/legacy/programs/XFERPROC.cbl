       IDENTIFICATION DIVISION.
       PROGRAM-ID. XFERPROC.
       AUTHOR. RJT.
      *****************************************************************
      * XFERPROC - DAILY TRANSACTION POSTING
      *
      * CHANGE LOG
      * 1989-03 RJT INITIAL VERSION (DP/WD ONLY)
      * 1991-07 DMK ADD XF TRANSACTION TYPE
      * 1994-02 DMK OD COUNTER FOR CHK ACCOUNTS
      * 1998-11 RJT Y2K REMEDIATION - DATES CARRIED AS YYDDD, SEE
      *             DATEUTIL FOR EXPANSION
      * 2003-05 LPW RAISE REF TABLE TO 5000 ENTRIES
      * 2007-10 LPW REMOVE PER-TXN LIMIT CHECK (SEE 2020)
      *****************************************************************
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CTL-FILE ASSIGN TO CTLCARD
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-CTL.
           SELECT ACCT-IN ASSIGN TO ACCTIN
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-AIN.
           SELECT ACCT-OUT ASSIGN TO ACCTOUT
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-AOUT.
           SELECT TXN-FILE ASSIGN TO TXNIN
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-TXN.
           SELECT POST-FILE ASSIGN TO POSTED
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-POST.
           SELECT REJ-FILE ASSIGN TO REJECTS
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-REJ.
       DATA DIVISION.
       FILE SECTION.
       FD  CTL-FILE.
       01  CTL-REC                     PIC 9(5).
       FD  ACCT-IN.
       01  ACCT-IN-REC                 PIC X(100).
       FD  ACCT-OUT.
       01  ACCT-OUT-REC                PIC X(100).
       FD  TXN-FILE.
           COPY TXNREC.
       FD  POST-FILE.
       01  POST-REC                    PIC X(80).
       FD  REJ-FILE.
           COPY REJREC.
       WORKING-STORAGE SECTION.
           COPY ACCTREC.
           COPY ACCTREC REPLACING LEADING ==ACCT-== BY ==CTR-==.
       01  WS-FILE-STATUSES.
           05  WS-FS-CTL               PIC XX.
           05  WS-FS-AIN               PIC XX.
           05  WS-FS-AOUT              PIC XX.
           05  WS-FS-TXN               PIC XX.
           05  WS-FS-POST              PIC XX.
           05  WS-FS-REJ               PIC XX.
       01  WS-BUSDATE                  PIC 9(5).
       01  WS-SWITCHES.
           05  WS-TXN-EOF-SW           PIC X VALUE 'N'.
               88  TXN-EOF             VALUE 'Y'.
           05  WS-AIN-EOF-SW           PIC X VALUE 'N'.
               88  AIN-EOF             VALUE 'Y'.
           05  WS-FOUND-SW             PIC X.
               88  ACCT-FOUND          VALUE 'Y'.
           05  WS-CTR-FOUND-SW         PIC X.
               88  CTR-FOUND           VALUE 'Y'.
           05  WS-DUP-SW               PIC X.
               88  REF-IS-DUP          VALUE 'Y'.
           05  WS-POSTED-SW            PIC X.
               88  TXN-POSTED          VALUE 'Y'.
       01  WS-REJ-CODE                 PIC X(3).
       01  WS-CHK-FOUND                PIC X.
       01  WS-CHK-STATUS               PIC X.
       01  WS-LOOKUP-KEY               PIC 9(10).
       01  WS-PRIOR-BAL                PIC S9(11)V99.
       01  WS-COUNTERS.
           05  WS-CNT-READ             PIC 9(7) VALUE ZERO.
           05  WS-CNT-POSTED           PIC 9(7) VALUE ZERO.
           05  WS-CNT-REJ              PIC 9(7) VALUE ZERO.
           05  WS-CNT-BADTYPE          PIC 9(7) VALUE ZERO.
       01  WS-ACCT-CNT                 PIC 9(4) COMP VALUE ZERO.
       01  WS-IX-1                     PIC 9(4) COMP.
       01  WS-IX-2                     PIC 9(4) COMP.
       01  WS-RX                       PIC 9(4) COMP.
       01  WS-REF-CNT                  PIC 9(4) COMP VALUE ZERO.
       01  WS-LAST-RUN-ID              PIC X(8) VALUE SPACES.
       01  WS-ACCT-TBL.
           05  WS-TE OCCURS 1 TO 500 TIMES
                     DEPENDING ON WS-ACCT-CNT
                     ASCENDING KEY IS WS-TE-KEY
                     INDEXED BY TX.
               10  WS-TE-KEY           PIC 9(10).
               10  WS-TE-REST          PIC X(90).
       01  WS-REF-TBL.
           05  WS-REF-ENT              PIC X(20) OCCURS 5000 TIMES.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT
           PERFORM 2000-PROCESS-TXN UNTIL TXN-EOF
           PERFORM 8000-REWRITE-MASTER
           PERFORM 9000-TERM
           STOP RUN.
       1000-INIT.
           OPEN INPUT CTL-FILE
           IF WS-FS-CTL NOT = '00'
               DISPLAY 'XFERPROC OPEN CTLCARD FS=' WS-FS-CTL
               PERFORM 9900-ABEND
           END-IF
           READ CTL-FILE INTO WS-BUSDATE
           CLOSE CTL-FILE
           OPEN INPUT TXN-FILE
           OPEN OUTPUT POST-FILE
           OPEN OUTPUT REJ-FILE
           IF WS-FS-TXN NOT = '00' OR WS-FS-POST NOT = '00'
              OR WS-FS-REJ NOT = '00'
               DISPLAY 'XFERPROC OPEN ERROR ' WS-FS-TXN WS-FS-POST
                       WS-FS-REJ
               PERFORM 9900-ABEND
           END-IF
           PERFORM 1100-LOAD-MASTER
           PERFORM 1200-READ-TXN.
       1100-LOAD-MASTER.
           OPEN INPUT ACCT-IN
           IF WS-FS-AIN NOT = '00'
               DISPLAY 'XFERPROC OPEN ACCTIN FS=' WS-FS-AIN
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
           CLOSE ACCT-IN.
       1200-READ-TXN.
           READ TXN-FILE
               AT END
                   SET TXN-EOF TO TRUE
               NOT AT END
                   ADD 1 TO WS-CNT-READ
           END-READ.
       2000-PROCESS-TXN.
           MOVE SPACES TO WS-REJ-CODE
           MOVE 'N' TO WS-POSTED-SW
           PERFORM 2010-DUP-CHECK
           IF WS-REJ-CODE = SPACES
               EVALUATE TXN-TYPE
                   WHEN 'DP'
                       PERFORM 2100-APPLY-DEPOSIT
                   WHEN 'WD'
                       PERFORM 2200-APPLY-WITHDRAWAL
                   WHEN 'XF'
                       PERFORM 2300-APPLY-TRANSFER
                   WHEN OTHER
                       ADD 1 TO WS-CNT-BADTYPE
               END-EVALUATE
           END-IF
           IF WS-REJ-CODE NOT = SPACES
               PERFORM 2900-WRITE-REJECT
           ELSE
               IF TXN-POSTED
                   PERFORM 2800-WRITE-POSTED
               END-IF
           END-IF
           PERFORM 1200-READ-TXN.
       2010-DUP-CHECK.
      * CHANNEL RETRY GUARD
           MOVE 'N' TO WS-DUP-SW
           IF TXN-REF NOT = SPACES
               PERFORM VARYING WS-RX FROM 1 BY 1
                   UNTIL WS-RX > WS-REF-CNT OR REF-IS-DUP
                   IF WS-REF-ENT(WS-RX) = TXN-REF
                       MOVE 'Y' TO WS-DUP-SW
                   END-IF
               END-PERFORM
               IF REF-IS-DUP
                   MOVE 'DUP' TO WS-REJ-CODE
               END-IF
           END-IF.
       2020-LIMIT-CHECK.
      *    IF TXN-AMOUNT > 9999999.99
      *        MOVE 'LIM' TO WS-REJ-CODE
      *    END-IF.
           CONTINUE.
       2100-APPLY-DEPOSIT.
           MOVE TXN-ACCT TO WS-LOOKUP-KEY
           PERFORM 2500-FIND-ACCT
           MOVE WS-FOUND-SW TO WS-CHK-FOUND
           MOVE ACCT-STATUS TO WS-CHK-STATUS
           PERFORM 2510-CHECK-STATUS
           IF WS-REJ-CODE = SPACES
               ADD TXN-AMOUNT TO ACCT-BALANCE
               MOVE WS-BUSDATE TO ACCT-LAST-ACT-DATE
               MOVE ACCT-REC TO WS-TE(WS-IX-1)
               MOVE 'Y' TO WS-POSTED-SW
           END-IF.
       2200-APPLY-WITHDRAWAL.
           MOVE TXN-ACCT TO WS-LOOKUP-KEY
           PERFORM 2500-FIND-ACCT
           MOVE WS-FOUND-SW TO WS-CHK-FOUND
           MOVE ACCT-STATUS TO WS-CHK-STATUS
           PERFORM 2510-CHECK-STATUS
           IF WS-REJ-CODE = SPACES
               PERFORM 2550-CHECK-FUNDS
           END-IF
           IF WS-REJ-CODE = SPACES
               PERFORM 2560-DEBIT-ACCT
               MOVE ACCT-REC TO WS-TE(WS-IX-1)
               MOVE 'Y' TO WS-POSTED-SW
           END-IF.
       2300-APPLY-TRANSFER.
           MOVE TXN-ACCT TO WS-LOOKUP-KEY
           PERFORM 2500-FIND-ACCT
           MOVE WS-FOUND-SW TO WS-CHK-FOUND
           MOVE ACCT-STATUS TO WS-CHK-STATUS
           PERFORM 2510-CHECK-STATUS
           IF WS-REJ-CODE = SPACES
               MOVE TXN-CTR-ACCT TO WS-LOOKUP-KEY
               PERFORM 2505-FIND-CTR
               MOVE WS-CTR-FOUND-SW TO WS-CHK-FOUND
               MOVE CTR-STATUS TO WS-CHK-STATUS
               PERFORM 2510-CHECK-STATUS
           END-IF
           IF WS-REJ-CODE = SPACES
               PERFORM 2550-CHECK-FUNDS
           END-IF
           IF WS-REJ-CODE = SPACES
               PERFORM 2560-DEBIT-ACCT
               ADD TXN-AMOUNT TO CTR-BALANCE
               MOVE WS-BUSDATE TO CTR-LAST-ACT-DATE
               MOVE ACCT-REC TO WS-TE(WS-IX-1)
               MOVE CTR-REC TO WS-TE(WS-IX-2)
               MOVE 'Y' TO WS-POSTED-SW
           END-IF.
       2500-FIND-ACCT.
           MOVE 'N' TO WS-FOUND-SW
           SEARCH ALL WS-TE
               AT END
                   MOVE 'N' TO WS-FOUND-SW
               WHEN WS-TE-KEY(TX) = WS-LOOKUP-KEY
                   MOVE 'Y' TO WS-FOUND-SW
                   SET WS-IX-1 TO TX
                   MOVE WS-TE(TX) TO ACCT-REC
           END-SEARCH.
       2505-FIND-CTR.
           MOVE 'N' TO WS-CTR-FOUND-SW
           SEARCH ALL WS-TE
               AT END
                   MOVE 'N' TO WS-CTR-FOUND-SW
               WHEN WS-TE-KEY(TX) = WS-LOOKUP-KEY
                   MOVE 'Y' TO WS-CTR-FOUND-SW
                   SET WS-IX-2 TO TX
                   MOVE WS-TE(TX) TO CTR-REC
           END-SEARCH.
       2510-CHECK-STATUS.
           IF WS-CHK-FOUND NOT = 'Y'
               MOVE 'NOA' TO WS-REJ-CODE
           ELSE
               IF WS-CHK-STATUS = 'C'
                   MOVE 'CLS' TO WS-REJ-CODE
               ELSE
                   IF WS-CHK-STATUS = 'F'
                       MOVE 'FRZ' TO WS-REJ-CODE
                   END-IF
               END-IF
           END-IF.
       2550-CHECK-FUNDS.
           IF ACCT-PRODUCT NOT = 'CHK'
               IF TXN-AMOUNT > ACCT-BALANCE
                   MOVE 'NSF' TO WS-REJ-CODE
               END-IF
           END-IF.
       2560-DEBIT-ACCT.
           MOVE ACCT-BALANCE TO WS-PRIOR-BAL
           SUBTRACT TXN-AMOUNT FROM ACCT-BALANCE
           IF ACCT-PRODUCT = 'CHK'
               IF ACCT-BALANCE < 0 AND WS-PRIOR-BAL >= 0
                   ADD 1 TO ACCT-OD-COUNT
               END-IF
           END-IF
           MOVE WS-BUSDATE TO ACCT-LAST-ACT-DATE.
       2800-WRITE-POSTED.
           WRITE POST-REC FROM TXN-REC
           ADD 1 TO WS-CNT-POSTED
           IF TXN-REF NOT = SPACES AND WS-REF-CNT < 5000
               ADD 1 TO WS-REF-CNT
               MOVE TXN-REF TO WS-REF-ENT(WS-REF-CNT)
           END-IF.
       2900-WRITE-REJECT.
           MOVE TXN-REC TO REJ-TXN-IMAGE
           MOVE WS-REJ-CODE TO REJ-REASON
           WRITE REJ-REC
           ADD 1 TO WS-CNT-REJ.
       2950-WRITE-AUDIT.
           DISPLAY 'AUDIT ' TXN-ID ' ' TXN-TYPE ' ' WS-REJ-CODE.
       8000-REWRITE-MASTER.
           OPEN OUTPUT ACCT-OUT
           IF WS-FS-AOUT NOT = '00'
               DISPLAY 'XFERPROC OPEN ACCTOUT FS=' WS-FS-AOUT
               PERFORM 9900-ABEND
           END-IF
           PERFORM VARYING WS-IX-1 FROM 1 BY 1
               UNTIL WS-IX-1 > WS-ACCT-CNT
               WRITE ACCT-OUT-REC FROM WS-TE(WS-IX-1)
           END-PERFORM
           CLOSE ACCT-OUT.
       9000-TERM.
           CLOSE TXN-FILE POST-FILE REJ-FILE
           DISPLAY 'XFERPROC BUSDATE ' WS-BUSDATE
           DISPLAY 'XFERPROC READ    ' WS-CNT-READ
           DISPLAY 'XFERPROC POSTED  ' WS-CNT-POSTED
           DISPLAY 'XFERPROC REJECT  ' WS-CNT-REJ.
       9900-ABEND.
           MOVE 16 TO RETURN-CODE
           STOP RUN.
