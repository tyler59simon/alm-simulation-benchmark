      *****************************************************************
      * REJREC   - REJECT RECORD                    LRECL=83
      *****************************************************************
       01  REJ-REC.
           05  REJ-TXN-IMAGE           PIC X(80).
           05  REJ-REASON              PIC X(3).
               88  REJ-DUP             VALUE 'DUP'.
               88  REJ-NSF             VALUE 'NSF'.
               88  REJ-FROZEN          VALUE 'FRZ'.
               88  REJ-CLOSED          VALUE 'CLS'.
               88  REJ-NO-ACCT         VALUE 'NOA'.
