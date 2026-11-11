       IDENTIFICATION DIVISION.
       PROGRAM-ID. FEEASSES.
       AUTHOR. DMK.
      *****************************************************************
      * FEEASSES - MONTH END FEE ASSESSMENT (CHECKING)
      *
      * CHANGE LOG
      * 1994-03 DMK INITIAL VERSION
      * 1996-10 DMK ADD MAINTENANCE FEE
      * 1998-11 RJT Y2K REMEDIATION - EOM TEST VIA DATEUTIL
      * 2001-06 LPW FROZEN ACCOUNTS NOW ASSESSED
      * 2009-01 TGB OD FEE PER EVENT, NOT PER MONTH
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
           SELECT POST-FILE ASSIGN TO POSTED
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-POST.
       DATA DIVISION.
       FILE SECTION.
       FD  CTL-FILE.
       01  CTL-REC                     PIC 9(5).
       FD  ACCT-IN.
           COPY ACCTREC.
       FD  ACCT-OUT.
       01  ACCT-OUT-REC                PIC X(100).
       FD  POST-FILE.
       01  POST-REC                    PIC X(80).
       WORKING-STORAGE SECTION.
           COPY TXNREC.
       01  WS-FS-CTL                   PIC XX.
       01  WS-FS-AIN                   PIC XX.
       01  WS-FS-AOUT                  PIC XX.
       01  WS-FS-POST                  PIC XX.
       01  WS-BUSDATE                  PIC 9(5).
       01  WS-EOF-SW                   PIC X VALUE 'N'.
           88  ACCT-EOF                VALUE 'Y'.
       01  WS-PEOF-SW                  PIC X VALUE 'N'.
           88  POST-EOF                VALUE 'Y'.
       01  WS-ME-SW                    PIC X VALUE 'N'.
           88  MONTH-END               VALUE 'Y'.
       01  WS-DU-PARM.
           05  WS-DU-FUNC              PIC X(2).
           05  WS-DU-JUL               PIC 9(5).
           05  WS-DU-YYYY              PIC 9(4).
           05  WS-DU-MM                PIC 9(2).
           05  WS-DU-DD                PIC 9(2).
           05  WS-DU-FLAG              PIC X.
           05  WS-DU-RC                PIC 9(2).
       01  WS-NEWID.
           05  FILLER                  PIC X VALUE 'B'.
           05  WS-ID-DATE              PIC 9(5).
           05  WS-ID-SEQ               PIC 9(6).
       01  WS-SEQ                      PIC 9(6) VALUE ZERO.
       01  WS-FEE-AMTS.
           05  WS-MF-FEE               PIC 9(3)V99 VALUE 5.00.
           05  WS-MF-MIN               PIC 9(5)V99 VALUE 500.00.
           05  WS-OD-FEE               PIC 9(3)V99 VALUE 35.00.
       01  WS-BAL-BEFORE               PIC S9(11)V99.
       01  WS-FEE-TOT                  PIC 9(9)V99.
       01  WS-CNT-IN                   PIC 9(7) VALUE ZERO.
       01  WS-CNT-MF                   PIC 9(7) VALUE ZERO.
       01  WS-CNT-OD                   PIC 9(7) VALUE ZERO.
       01  WS-GRACE-DAYS               PIC 99 VALUE 05.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT
           PERFORM 2000-PROCESS-ACCT UNTIL ACCT-EOF
           PERFORM 9000-TERM
           STOP RUN.
       1000-INIT.
           OPEN INPUT CTL-FILE
           IF WS-FS-CTL NOT = '00'
               DISPLAY 'FEEASSES OPEN CTLCARD FS=' WS-FS-CTL
               PERFORM 9900-ABEND
           END-IF
           READ CTL-FILE INTO WS-BUSDATE
           CLOSE CTL-FILE
           MOVE 'ME' TO WS-DU-FUNC
           MOVE WS-BUSDATE TO WS-DU-JUL
           CALL 'DATEUTIL' USING WS-DU-PARM
           MOVE WS-DU-FLAG TO WS-ME-SW
           MOVE WS-BUSDATE TO WS-ID-DATE
           PERFORM 1100-COUNT-JOURNAL
           OPEN INPUT ACCT-IN
           OPEN OUTPUT ACCT-OUT
           OPEN EXTEND POST-FILE
           IF WS-FS-AIN NOT = '00' OR WS-FS-AOUT NOT = '00'
              OR WS-FS-POST NOT = '00'
               DISPLAY 'FEEASSES OPEN ERROR ' WS-FS-AIN WS-FS-AOUT
                       WS-FS-POST
               PERFORM 9900-ABEND
           END-IF
           PERFORM 1200-READ-ACCT.
       1100-COUNT-JOURNAL.
           OPEN INPUT POST-FILE
           IF WS-FS-POST NOT = '00'
               DISPLAY 'FEEASSES OPEN POSTED FS=' WS-FS-POST
               PERFORM 9900-ABEND
           END-IF
           PERFORM UNTIL POST-EOF
               READ POST-FILE INTO TXN-REC
                   AT END
                       SET POST-EOF TO TRUE
                   NOT AT END
                       IF TXN-ID(1:1) = 'B'
                           ADD 1 TO WS-SEQ
                       END-IF
               END-READ
           END-PERFORM
           CLOSE POST-FILE.
       1200-READ-ACCT.
           READ ACCT-IN
               AT END
                   SET ACCT-EOF TO TRUE
               NOT AT END
                   ADD 1 TO WS-CNT-IN
           END-READ.
       2000-PROCESS-ACCT.
           IF MONTH-END
               IF ACCT-PRODUCT = 'CHK'
                   IF ACCT-ACTIVE OR ACCT-FROZEN
                       PERFORM 2100-ASSESS-FEES
                   END-IF
               END-IF
           END-IF
           WRITE ACCT-OUT-REC FROM ACCT-REC
           PERFORM 1200-READ-ACCT.
       2100-ASSESS-FEES.
           MOVE ACCT-BALANCE TO WS-BAL-BEFORE
           IF WS-BAL-BEFORE < WS-MF-MIN
               PERFORM 2200-MAINT-FEE
           END-IF
           IF ACCT-OD-COUNT > 0
               PERFORM 2300-OVERDRAFT-FEE
           END-IF
           MOVE ZERO TO ACCT-OD-COUNT.
       2200-MAINT-FEE.
           SUBTRACT WS-MF-FEE FROM ACCT-BALANCE
           MOVE WS-MF-FEE TO WS-FEE-TOT
           MOVE 'MF' TO TXN-TYPE
           PERFORM 2900-WRITE-JOURNAL
           ADD 1 TO WS-CNT-MF.
       2300-OVERDRAFT-FEE.
      *    IF ACCT-OD-COUNT > 3
      *        MOVE 50.00 TO WS-OD-FEE
      *    END-IF
           COMPUTE WS-FEE-TOT = ACCT-OD-COUNT * WS-OD-FEE
           SUBTRACT WS-FEE-TOT FROM ACCT-BALANCE
           MOVE 'OD' TO TXN-TYPE
           PERFORM 2900-WRITE-JOURNAL
           ADD 1 TO WS-CNT-OD.
       2400-GRACE-WAIVER.
           IF ACCT-LAST-ACT-DATE > WS-BUSDATE
               MOVE ZERO TO WS-GRACE-DAYS
           END-IF.
       2900-WRITE-JOURNAL.
           ADD 1 TO WS-SEQ
           MOVE WS-SEQ TO WS-ID-SEQ
           MOVE WS-NEWID TO TXN-ID
           MOVE ACCT-NUMBER TO TXN-ACCT
           MOVE WS-FEE-TOT TO TXN-AMOUNT
           MOVE WS-BUSDATE TO TXN-DATE
           MOVE ZEROS TO TXN-CTR-ACCT
           MOVE SPACES TO TXN-REF
           MOVE SPACES TO TXN-REC(71:10)
           WRITE POST-REC FROM TXN-REC.
       9000-TERM.
           CLOSE ACCT-IN ACCT-OUT POST-FILE
           DISPLAY 'FEEASSES BUSDATE ' WS-BUSDATE
           DISPLAY 'FEEASSES MF      ' WS-CNT-MF
           DISPLAY 'FEEASSES OD      ' WS-CNT-OD.
       9900-ABEND.
           MOVE 16 TO RETURN-CODE
           STOP RUN.
