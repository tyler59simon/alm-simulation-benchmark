       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATEUTIL.
       AUTHOR. RJT.
      *****************************************************************
      * DATEUTIL - JULIAN DATE SUBROUTINE
      * CALL 'DATEUTIL' USING LK-DU-PARM
      *   FUNC CJ  CONVERT ONLY
      *   FUNC DM  DAY OF MONTH IN LK-DU-DD
      *   FUNC ME  LK-DU-FLAG = Y IF LAST DAY OF MONTH
      *   FUNC LF  LK-DU-FLAG = Y IF LAST DAY OF FEBRUARY
      *
      * CHANGE LOG
      * 1989-02 RJT INITIAL VERSION
      * 1992-09 DMK ADD ME FUNCTION FOR EOM JOBS
      * 1998-11 RJT Y2K REMEDIATION - 4 DIGIT YEAR IN LK-DU-YYYY
      * 1999-06 RJT Y2K RETEST, LEAP 2000 CHECKED OK
      * 2004-03 LPW ADD LF FUNCTION FOR INTCALC
      *****************************************************************
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-YY                       PIC 99.
       01  WS-DDD                      PIC 999.
       01  WS-REM                      PIC 999.
       01  WS-M                        PIC 99.
       01  WS-LEAP-SW                  PIC X VALUE 'N'.
           88  WS-LEAP                 VALUE 'Y'.
       01  WS-OLD-CUTOFF               PIC 99 VALUE 50.
       01  WS-MONTH-TBL                PIC X(24)
                       VALUE '312831303130313130313031'.
       01  WS-MONTH-WRK                PIC X(24).
       01  WS-MDAYS REDEFINES WS-MONTH-WRK.
           05  WS-MD                   PIC 99 OCCURS 12 TIMES.
       LINKAGE SECTION.
       01  LK-DU-PARM.
           05  LK-DU-FUNC              PIC X(2).
           05  LK-DU-JUL               PIC 9(5).
           05  LK-DU-YYYY              PIC 9(4).
           05  LK-DU-MM                PIC 9(2).
           05  LK-DU-DD                PIC 9(2).
           05  LK-DU-FLAG              PIC X.
           05  LK-DU-RC                PIC 9(2).
       PROCEDURE DIVISION USING LK-DU-PARM.
       0000-MAIN.
           MOVE 'N' TO LK-DU-FLAG
           MOVE ZERO TO LK-DU-RC
           PERFORM 9000-CONVERT-JULIAN
           IF LK-DU-RC = ZERO
               EVALUATE LK-DU-FUNC
                   WHEN 'CJ'
                       CONTINUE
                   WHEN 'DM'
                       CONTINUE
                   WHEN 'ME'
                       PERFORM 1000-CHECK-MONTH-END
                   WHEN 'LF'
                       PERFORM 1100-CHECK-LAST-FEB
                   WHEN OTHER
                       MOVE 12 TO LK-DU-RC
               END-EVALUATE
           END-IF
           GOBACK.
       1000-CHECK-MONTH-END.
           IF LK-DU-DD = WS-MD(LK-DU-MM)
               MOVE 'Y' TO LK-DU-FLAG
           END-IF.
       1100-CHECK-LAST-FEB.
           IF LK-DU-MM = 2 AND LK-DU-DD = WS-MD(2)
               MOVE 'Y' TO LK-DU-FLAG
           END-IF.
       1200-OLD-WINDOW-CHECK.
      *    IF WS-YY < WS-OLD-CUTOFF
      *        COMPUTE LK-DU-YYYY = 2000 + WS-YY
           CONTINUE.
       9000-CONVERT-JULIAN.
           DIVIDE LK-DU-JUL BY 1000 GIVING WS-YY REMAINDER WS-DDD
           IF WS-YY < 70
               COMPUTE LK-DU-YYYY = 2000 + WS-YY
           ELSE
               COMPUTE LK-DU-YYYY = 1900 + WS-YY
           END-IF
           MOVE WS-MONTH-TBL TO WS-MONTH-WRK
           MOVE 'N' TO WS-LEAP-SW
           IF FUNCTION MOD(LK-DU-YYYY, 4) = 0
               IF FUNCTION MOD(LK-DU-YYYY, 100) NOT = 0
                  OR FUNCTION MOD(LK-DU-YYYY, 400) = 0
                   MOVE 'Y' TO WS-LEAP-SW
                   MOVE 29 TO WS-MD(2)
               END-IF
           END-IF
           IF WS-DDD = 0 OR WS-DDD > 366
               MOVE 8 TO LK-DU-RC
           ELSE
               MOVE WS-DDD TO WS-REM
               PERFORM VARYING WS-M FROM 1 BY 1
                   UNTIL WS-M > 12 OR WS-REM <= WS-MD(WS-M)
                   SUBTRACT WS-MD(WS-M) FROM WS-REM
               END-PERFORM
               IF WS-M > 12
                   MOVE 8 TO LK-DU-RC
               ELSE
                   MOVE WS-M TO LK-DU-MM
                   MOVE WS-REM TO LK-DU-DD
               END-IF
           END-IF.
