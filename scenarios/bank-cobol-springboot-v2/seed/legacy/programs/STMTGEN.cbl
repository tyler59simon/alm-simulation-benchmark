       IDENTIFICATION DIVISION.
       PROGRAM-ID. STMTGEN.
       AUTHOR. RJT.
      *****************************************************************
      * STMTGEN  - MONTH END CUSTOMER STATEMENT EXTRACT
      *
      * CHANGE LOG
      * 1991-05 RJT INITIAL VERSION
      * 1995-11 DMK ADD FEES COLUMN
      * 1998-11 RJT Y2K REMEDIATION - NAME OF OUTPUT DSN CARRIES YYYYMM
      * 2005-02 LPW INCLUDE FROZEN/CLOSED ACCOUNTS
      * 2008-07 TGB PRINT VENDOR NEEDS 120 BYTE LINES
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
           SELECT POST-FILE ASSIGN TO POSTED
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-POST.
           SELECT STMT-FILE ASSIGN TO STMTOUT
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-FS-STMT.
       DATA DIVISION.
       FILE SECTION.
       FD  CTL-FILE.
       01  CTL-REC                     PIC 9(5).
       FD  ACCT-IN.
           COPY ACCTREC.
       FD  POST-FILE.
       01  POST-REC                    PIC X(80).
       FD  STMT-FILE.
       01  STMT-REC                    PIC X(120).
       WORKING-STORAGE SECTION.
           COPY TXNREC.
       01  WS-FS-CTL                   PIC XX.
       01  WS-FS-AIN                   PIC XX.
       01  WS-FS-POST                  PIC XX.
       01  WS-FS-STMT                  PIC XX.
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
       01  WS-SUM-CNT                  PIC 9(4) COMP VALUE ZERO.
       01  WS-SX                       PIC 9(4) COMP.
       01  WS-SUM-TBL.
           05  WS-SUM-ENT OCCURS 500 TIMES.
               10  WS-SUM-ACCT         PIC 9(10).
               10  WS-SUM-INT          PIC 9(9)V99.
               10  WS-SUM-FEE          PIC 9(9)V99.
       01  WS-FOUND-SW                 PIC X.
           88  SUM-FOUND               VALUE 'Y'.
       01  WS-LINE.
           05  WS-L-ACCT               PIC 9(10).
           05  FILLER                  PIC X VALUE SPACE.
           05  WS-L-PROD               PIC X(3).
           05  FILLER                  PIC X VALUE SPACE.
           05  WS-L-STAT               PIC X.
           05  FILLER                  PIC X VALUE SPACE.
           05  WS-L-BAL                PIC -ZZZ,ZZZ,ZZ9.99.
           05  FILLER                  PIC X VALUE SPACE.
           05  WS-L-INT                PIC ZZ,ZZ9.99.
           05  FILLER                  PIC X VALUE SPACE.
           05  WS-L-FEE                PIC ZZ,ZZ9.99.
           05  FILLER                  PIC X(68) VALUE SPACES.
       01  WS-HDR-LINE                 PIC X(120) VALUE SPACES.
       01  WS-CNT-STMT                 PIC 9(7) VALUE ZERO.
       01  WS-PAGE-NO                  PIC 9(3) VALUE ZERO.
       PROCEDURE DIVISION.
       0000-MAIN.
           PERFORM 1000-INIT
           IF MONTH-END
               PERFORM 1100-LOAD-JOURNAL
               PERFORM 2000-PROCESS-ACCT UNTIL ACCT-EOF
           END-IF
           PERFORM 9000-TERM
           STOP RUN.
       1000-INIT.
           OPEN INPUT CTL-FILE
           IF WS-FS-CTL NOT = '00'
               DISPLAY 'STMTGEN OPEN CTLCARD FS=' WS-FS-CTL
               PERFORM 9900-ABEND
           END-IF
           READ CTL-FILE INTO WS-BUSDATE
           CLOSE CTL-FILE
           MOVE 'ME' TO WS-DU-FUNC
           MOVE WS-BUSDATE TO WS-DU-JUL
           CALL 'DATEUTIL' USING WS-DU-PARM
           MOVE WS-DU-FLAG TO WS-ME-SW
           IF MONTH-END
               OPEN INPUT ACCT-IN POST-FILE
               OPEN OUTPUT STMT-FILE
               IF WS-FS-AIN NOT = '00' OR WS-FS-POST NOT = '00'
                  OR WS-FS-STMT NOT = '00'
                   DISPLAY 'STMTGEN OPEN ERROR ' WS-FS-AIN WS-FS-POST
                           WS-FS-STMT
                   PERFORM 9900-ABEND
               END-IF
               PERFORM 1200-READ-ACCT
           END-IF.
       1100-LOAD-JOURNAL.
           PERFORM UNTIL POST-EOF
               READ POST-FILE INTO TXN-REC
                   AT END
                       SET POST-EOF TO TRUE
                   NOT AT END
                       IF TXN-INTEREST OR TXN-MAINT-FEE OR TXN-OD-FEE
                           PERFORM 1150-ADD-TO-SUMMARY
                       END-IF
               END-READ
           END-PERFORM.
       1150-ADD-TO-SUMMARY.
           MOVE 'N' TO WS-FOUND-SW
           PERFORM VARYING WS-SX FROM 1 BY 1
               UNTIL WS-SX > WS-SUM-CNT OR SUM-FOUND
               IF WS-SUM-ACCT(WS-SX) = TXN-ACCT
                   MOVE 'Y' TO WS-FOUND-SW
               END-IF
           END-PERFORM
           IF NOT SUM-FOUND
               ADD 1 TO WS-SUM-CNT
               MOVE WS-SUM-CNT TO WS-SX
               MOVE TXN-ACCT TO WS-SUM-ACCT(WS-SX)
               MOVE ZERO TO WS-SUM-INT(WS-SX) WS-SUM-FEE(WS-SX)
           ELSE
               SUBTRACT 1 FROM WS-SX
           END-IF
           IF TXN-INTEREST
               ADD TXN-AMOUNT TO WS-SUM-INT(WS-SX)
           ELSE
               ADD TXN-AMOUNT TO WS-SUM-FEE(WS-SX)
           END-IF.
       1200-READ-ACCT.
           READ ACCT-IN
               AT END
                   SET ACCT-EOF TO TRUE
           END-READ.
       2000-PROCESS-ACCT.
           MOVE ACCT-NUMBER TO WS-L-ACCT
           MOVE ACCT-PRODUCT TO WS-L-PROD
           MOVE ACCT-STATUS TO WS-L-STAT
           MOVE ACCT-BALANCE TO WS-L-BAL
           MOVE ZERO TO WS-L-INT WS-L-FEE
           PERFORM 2100-LOOKUP-SUMMARY
           WRITE STMT-REC FROM WS-LINE
           ADD 1 TO WS-CNT-STMT
           PERFORM 1200-READ-ACCT.
       2100-LOOKUP-SUMMARY.
           MOVE 'N' TO WS-FOUND-SW
           PERFORM VARYING WS-SX FROM 1 BY 1
               UNTIL WS-SX > WS-SUM-CNT OR SUM-FOUND
               IF WS-SUM-ACCT(WS-SX) = ACCT-NUMBER
                   MOVE 'Y' TO WS-FOUND-SW
                   MOVE WS-SUM-INT(WS-SX) TO WS-L-INT
                   MOVE WS-SUM-FEE(WS-SX) TO WS-L-FEE
               END-IF
           END-PERFORM.
       2200-WRITE-HEADER.
           ADD 1 TO WS-PAGE-NO
           MOVE 'HARBOR POINT SAVINGS AND TRUST' TO WS-HDR-LINE
           WRITE STMT-REC FROM WS-HDR-LINE.
       9000-TERM.
           IF MONTH-END
               CLOSE ACCT-IN POST-FILE STMT-FILE
           END-IF
           DISPLAY 'STMTGEN BUSDATE ' WS-BUSDATE
           DISPLAY 'STMTGEN LINES   ' WS-CNT-STMT.
       9900-ABEND.
           MOVE 16 TO RETURN-CODE
           STOP RUN.
