      *****************************************************************
      * TXNREC   - TRANSACTION / POSTING JOURNAL RECORD   LRECL=80
      *****************************************************************
       01  TXN-REC.
           05  TXN-ID                  PIC X(12).
           05  TXN-ACCT                PIC 9(10).
           05  TXN-TYPE                PIC X(2).
               88  TXN-DEPOSIT         VALUE 'DP'.
               88  TXN-WITHDRAWAL      VALUE 'WD'.
               88  TXN-TRANSFER        VALUE 'XF'.
               88  TXN-INTEREST        VALUE 'IN'.
               88  TXN-OD-FEE          VALUE 'OD'.
               88  TXN-MAINT-FEE       VALUE 'MF'.
           05  TXN-AMOUNT              PIC 9(9)V99.
           05  TXN-DATE                PIC 9(5).
           05  TXN-CTR-ACCT            PIC 9(10).
           05  TXN-REF                 PIC X(20).
           05  FILLER                  PIC X(10).
