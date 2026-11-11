      *****************************************************************
      * ACCTREC  - ACCOUNT MASTER RECORD            LRECL=100
      * HARBOR POINT SAVINGS & TRUST - CORE DEPOSITS
      *****************************************************************
       01  ACCT-REC.
           05  ACCT-NUMBER             PIC 9(10).
           05  ACCT-PRODUCT            PIC X(3).
           05  ACCT-STATUS             PIC X.
               88  ACCT-ACTIVE         VALUE 'A'.
               88  ACCT-FROZEN         VALUE 'F'.
               88  ACCT-CLOSED         VALUE 'C'.
           05  ACCT-OPEN-DATE          PIC 9(5).
           05  ACCT-CUST-NAME          PIC X(30).
           05  ACCT-BALANCE            PIC S9(11)V99
                   SIGN IS LEADING SEPARATE CHARACTER.
           05  ACCT-ACCRUED-INT        PIC S9(9)V9(6)
                   SIGN IS LEADING SEPARATE CHARACTER.
           05  ACCT-RATE               PIC 9V9(5).
           05  ACCT-LAST-ACT-DATE      PIC 9(5).
           05  ACCT-OD-COUNT           PIC 9(3).
           05  FILLER                  PIC X(7).
