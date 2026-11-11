       IDENTIFICATION DIVISION.
       PROGRAM-ID. INTCALC.
       AUTHOR. DMK.
      *****************************************************************
      * INTCALC  - DAILY INTEREST ACCRUAL
      *
      * CHANGE LOG
      * 1990-01 DMK INITIAL VERSION
      * 1993-04 DMK ADD MMA PRODUCT
      * 1998-11 RJT Y2K REMEDIATION - CALL DATEUTIL FOR DD
      * 2002-08 LPW SV2 PRODUCT ADDED TO TABLE
      * 2004-03 LPW FEB HANDLING VIA DATEUTIL LF
      * 2011-01 TGB RC=4 AT MONTH END FOR NIGHTLY COND
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
       DATA DIVISION.
       FILE SECTION.
       FD  CTL-FILE.
       01  CTL-REC                     PIC 9(5).
       FD  ACCT-IN.
           COPY ACCTREC.
       FD  ACCT-OUT.
       01  ACCT-OUT-REC                PIC X(100).
       WORKING-STORAGE SECTION.
       01  WS-FS-CTL                   PIC XX.
       01  WS-FS-AIN                   PIC XX.
       01  WS-FS-AOUT                  PIC XX.
       01  WS-BUSDATE                  PIC 9(5).
       01  WS-EOF-SW                   PIC X VALUE 'N'.
           88  ACCT-EOF                VALUE 'Y'.
       01  WS-DU-PARM.
           05  WS-DU-FUNC              PIC X(2).
           05  WS-DU-JUL               PIC 9(5).
           05  WS-DU-YYYY              PIC 9(4).
           05  WS-DU-MM                PIC 9(2).
           05  WS-DU-DD                PIC 9(2).
           05  WS-DU-FLAG              PIC X.
           05  WS-DU-RC                PIC 9(2).
       01  WS-DD                       PIC 99.
       01  WS-FEB-LAST                 PIC X VALUE 'N'.
       01  WS-PROD-TABLE.
           05  FILLER                  PIC X(6) VALUE 'SV1360'.
           05  FILLER                  PIC X(6) VALUE 'SV2365'.
           05  FILLER                  PIC X(6) VALUE 'MMA365'.
       01  WS-PROD-TBL REDEFINES WS-PROD-TABLE.
           05  WS-PT OCCURS 3 TIMES INDEXED BY PX.
               10  WS-PT-CODE          PIC X(3).
               10  WS-PT-BASIS         PIC 9(3).
       01  WS-PT-SW                    PIC X.
           88  WS-PT-FOUND             VALUE 'Y'.
       01  WS-BASIS                    PIC 9(3).
       01  WS-DAYS                     PIC 99.
       01  WS-ACCR                     PIC S9(9)V9(6).
       01  WS-TOT-ACCR                 PIC S9(11)V9(6) VALUE ZERO.
       01  WS-MIN-BAL                  PIC 9(5)V99 VALUE 100.00.
       01  WS-CNT-IN                   PIC 9(7) VALUE ZERO.
       01  WS-CNT-ACCR                 PIC 9(7) VALUE ZERO.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT
           PERFORM 2000-PROCESS-ACCT UNTIL ACCT-EOF
           PERFORM 9000-TERM
           STOP RUN.
       1000-INIT.
           OPEN INPUT CTL-FILE
           IF WS-FS-CTL NOT = '00'
               DISPLAY 'INTCALC OPEN CTLCARD FS=' WS-FS-CTL
               PERFORM 9900-ABEND
           END-IF
           READ CTL-FILE INTO WS-BUSDATE
           CLOSE CTL-FILE
           MOVE 'LF' TO WS-DU-FUNC
           MOVE WS-BUSDATE TO WS-DU-JUL
           CALL 'DATEUTIL' USING WS-DU-PARM
           MOVE WS-DU-DD TO WS-DD
           MOVE WS-DU-FLAG TO WS-FEB-LAST
           MOVE 'ME' TO WS-DU-FUNC
           CALL 'DATEUTIL' USING WS-DU-PARM
           IF WS-DU-FLAG = 'Y'
               MOVE 4 TO RETURN-CODE
           END-IF
           OPEN INPUT ACCT-IN
           OPEN OUTPUT ACCT-OUT
           IF WS-FS-AIN NOT = '00' OR WS-FS-AOUT NOT = '00'
               DISPLAY 'INTCALC OPEN ERROR ' WS-FS-AIN WS-FS-AOUT
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
           IF ACCT-STATUS = 'A' AND ACCT-BALANCE > 0
               PERFORM 2100-FIND-PRODUCT
               IF WS-PT-FOUND
                   PERFORM 2200-GET-DAYS
                   IF WS-DAYS > 0
                       PERFORM 2300-ACCRUE
                   END-IF
               END-IF
           END-IF
           WRITE ACCT-OUT-REC FROM ACCT-REC
           PERFORM 1100-READ-ACCT.
       2100-FIND-PRODUCT.
           MOVE 'N' TO WS-PT-SW
           SET PX TO 1
           SEARCH WS-PT
               AT END
                   MOVE 'N' TO WS-PT-SW
               WHEN WS-PT-CODE(PX) = ACCT-PRODUCT
                   MOVE 'Y' TO WS-PT-SW
                   MOVE WS-PT-BASIS(PX) TO WS-BASIS
           END-SEARCH.
       2200-GET-DAYS.
           IF WS-BASIS = 365
               MOVE 1 TO WS-DAYS
           ELSE
               IF WS-DD = 31
                   MOVE 0 TO WS-DAYS
               ELSE
                   IF WS-FEB-LAST = 'Y'
                       COMPUTE WS-DAYS = 30 - WS-DD + 1
                   ELSE
                       MOVE 1 TO WS-DAYS
                   END-IF
               END-IF
           END-IF.
       2300-ACCRUE.
           COMPUTE WS-ACCR = ACCT-BALANCE * ACCT-RATE
                             * WS-DAYS / WS-BASIS
           ADD WS-ACCR TO ACCT-ACCRUED-INT
           ADD WS-ACCR TO WS-TOT-ACCR
           ADD 1 TO WS-CNT-ACCR.
       2400-MIN-BAL-TEST.
      *    IF ACCT-BALANCE < WS-MIN-BAL
      *        MOVE ZERO TO WS-DAYS
      *    END-IF.
           CONTINUE.
       9000-TERM.
           CLOSE ACCT-IN ACCT-OUT
           DISPLAY 'INTCALC BUSDATE ' WS-BUSDATE
           DISPLAY 'INTCALC ACCTS   ' WS-CNT-IN
           DISPLAY 'INTCALC ACCRUED ' WS-CNT-ACCR.
       9900-ABEND.
           MOVE 16 TO RETURN-CODE
           STOP RUN.
