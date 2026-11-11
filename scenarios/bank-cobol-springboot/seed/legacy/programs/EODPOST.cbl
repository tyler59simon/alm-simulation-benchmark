       IDENTIFICATION DIVISION.
       PROGRAM-ID. EODPOST.
       AUTHOR. DMK.
      *****************************************************************
      * EODPOST  - MONTH END INTEREST POSTING
      *
      * CHANGE LOG
      * 1990-02 DMK INITIAL VERSION
      * 1998-11 RJT Y2K REMEDIATION - EOM TEST NOW VIA DATEUTIL
      * 1999-02 RJT Y2K REGRESSION OK
      * 2006-09 LPW JOURNAL RECORD FOR EACH POSTING (TYPE IN)
      * 2012-03 TGB COMPILER UPGRADE, RECOMPILED ONLY
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
       01  WS-POSTED                   PIC S9(9)V99.
       01  WS-TOT-POSTED               PIC S9(11)V99 VALUE ZERO.
       01  WS-CNT-IN                   PIC 9(7) VALUE ZERO.
       01  WS-CNT-POSTED               PIC 9(7) VALUE ZERO.
       01  WS-WORK-AMT                 PIC S9(9)V99 VALUE ZERO.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT
           PERFORM 2000-PROCESS-ACCT UNTIL ACCT-EOF
           PERFORM 9000-TERM
           STOP RUN.
       1000-INIT.
           OPEN INPUT CTL-FILE
           IF WS-FS-CTL NOT = '00'
               DISPLAY 'EODPOST OPEN CTLCARD FS=' WS-FS-CTL
               PERFORM 9900-ABEND
           END-IF
           READ CTL-FILE INTO WS-BUSDATE
           CLOSE CTL-FILE
           MOVE 'ME' TO WS-DU-FUNC
           MOVE WS-BUSDATE TO WS-DU-JUL
           CALL 'DATEUTIL' USING WS-DU-PARM
           MOVE WS-DU-FLAG TO WS-ME-SW
           MOVE WS-BUSDATE TO WS-ID-DATE
           OPEN INPUT ACCT-IN
           OPEN OUTPUT ACCT-OUT
           OPEN EXTEND POST-FILE
           IF WS-FS-AIN NOT = '00' OR WS-FS-AOUT NOT = '00'
              OR WS-FS-POST NOT = '00'
               DISPLAY 'EODPOST OPEN ERROR ' WS-FS-AIN WS-FS-AOUT
                       WS-FS-POST
               PERFORM 9900-ABEND
           END-IF
           PERFORM 1100-READ-ACCT.
       1100-READ-ACCT.
           READ ACCT-IN
               AT END
                   SET ACCT-EOF TO TRUE
               NOT AT END
                   ADD 1 TO WS-CNT-IN
           END-READ.
       2000-PROCESS-ACCT.
           IF MONTH-END
               IF ACCT-ACCRUED-INT > 0
                   PERFORM 2100-POST-INTEREST
               END-IF
           END-IF
           WRITE ACCT-OUT-REC FROM ACCT-REC
           PERFORM 1100-READ-ACCT.
       2100-POST-INTEREST.
           COMPUTE WS-POSTED ROUNDED MODE IS NEAREST-EVEN
               = ACCT-ACCRUED-INT
           IF WS-POSTED > 0
               ADD WS-POSTED TO ACCT-BALANCE
               ADD WS-POSTED TO WS-TOT-POSTED
               PERFORM 2200-WRITE-JOURNAL
           END-IF
           MOVE ZERO TO ACCT-ACCRUED-INT.
       2200-WRITE-JOURNAL.
           ADD 1 TO WS-SEQ
           MOVE WS-SEQ TO WS-ID-SEQ
           MOVE SPACES TO TXN-REC
           MOVE WS-NEWID TO TXN-ID
           MOVE ACCT-NUMBER TO TXN-ACCT
           MOVE 'IN' TO TXN-TYPE
           MOVE WS-POSTED TO TXN-AMOUNT
           MOVE WS-BUSDATE TO TXN-DATE
           MOVE ZEROS TO TXN-CTR-ACCT
           WRITE POST-REC FROM TXN-REC
           ADD 1 TO WS-CNT-POSTED.
       2300-TRUNC-POST.
           COMPUTE WS-WORK-AMT = ACCT-ACCRUED-INT
           MOVE WS-WORK-AMT TO WS-POSTED.
       9000-TERM.
           CLOSE ACCT-IN ACCT-OUT POST-FILE
           DISPLAY 'EODPOST BUSDATE ' WS-BUSDATE
           DISPLAY 'EODPOST POSTED  ' WS-CNT-POSTED.
       9900-ABEND.
           MOVE 16 TO RETURN-CODE
           STOP RUN.
