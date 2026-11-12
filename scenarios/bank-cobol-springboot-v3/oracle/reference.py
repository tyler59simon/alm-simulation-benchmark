"""Reference model of the Harbor Point legacy nightly batch (see LEGACY_SPEC.md). Hidden from agents.

Generates the deterministic input dataset and the golden-master outputs the modernized system must match:
    python reference.py OUT_DIR        -> OUT_DIR/input/..., OUT_DIR/golden/...
Run with --check to also print the planted-fact self-checks (half-even vs half-up ties, 30/360 effects).
"""
import calendar
import random
import sys
from datetime import date, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP
from pathlib import Path

START, END = date(2025, 2, 1), date(2025, 3, 31)
BASIS = {'SV1': 360, 'SV2': 365, 'MMA': 365}
OD_FEE, MF_FEE, MF_THRESHOLD = Decimal('35.00'), Decimal('5.00'), Decimal('500.00')
C2, C6 = Decimal('0.01'), Decimal('0.000001')


# ---------- field formatting (fixed width, implied decimals) ----------
def julian(d):
    return f'{d.year % 100:02d}{d.timetuple().tm_yday:03d}'


def from_julian(s):
    yy, ddd = int(s[:2]), int(s[2:])
    year = 2000 + yy if yy < 70 else 1900 + yy
    return date(year, 1, 1) + timedelta(days=ddd - 1)


def unsigned(value, digits, decimals):
    return f'{int((value * 10 ** decimals).to_integral_value()):0{digits}d}'


def signed(value, digits, decimals):
    scaled = int((value * 10 ** decimals).to_integral_value())
    return ('-' if scaled < 0 else '+') + f'{abs(scaled):0{digits}d}'


def edit(value, pic):
    """COBOL numeric edit for pictures like -ZZZ,ZZZ,ZZ9.99 and ZZ,ZZ9.99."""
    sign = ''
    if pic.startswith('-'):
        sign, pic = ('-' if value < 0 else ' '), pic[1:]
    digits = str(int((abs(value) * 100).to_integral_value())).rjust(sum(c in 'Z9' for c in pic), '0')
    out, i, started = [], 0, False
    for c in pic:
        if c in 'Z9':
            d = digits[i]; i += 1
            if d != '0' or c == '9':
                started = True
            out.append(d if started else ' ')
        elif c == ',':
            out.append(',' if started else ' ')
        else:
            started = True
            out.append(c)
    return sign + ''.join(out)


class Acct:
    def __init__(self, number, product, status, opened, name, balance, rate):
        self.number, self.product, self.status, self.opened, self.name = number, product, status, opened, name
        self.balance, self.accrued, self.rate = Decimal(balance), Decimal('0'), Decimal(rate)
        self.last_act, self.od_count = opened, 0

    def record(self):
        r = (f'{self.number:010d}{self.product}{self.status}{julian(self.opened)}{self.name:<30.30}'
             f'{signed(self.balance, 13, 2)}{signed(self.accrued, 15, 6)}{unsigned(self.rate, 6, 5)}'
             f'{julian(self.last_act)}{self.od_count:03d}' + ' ' * 7)
        assert len(r) == 100, len(r)
        return r


def txn_record(tid, acct, typ, amount, d, ctr=0, ref=''):
    r = f'{tid:<12}{acct:010d}{typ}{unsigned(amount, 11, 2)}{julian(d)}{ctr:010d}{ref:<20.20}' + ' ' * 10
    assert len(r) == 80, len(r)
    return r


# ---------- dataset ----------
FIRST = ['MARY', 'JOHN', 'PATRICIA', 'ROBERT', 'LINDA', 'JAMES', 'BARBARA', 'MICHAEL', 'ELIZABETH', 'WILLIAM',
         'SUSAN', 'DAVID', 'JESSICA', 'RICHARD', 'KAREN', 'JOSEPH', 'NANCY', 'THOMAS', 'LISA', 'CHARLES']
LAST = ['OKAFOR', 'NGUYEN', 'GARCIA', 'MULLER', 'SMITH', 'KOWALSKI', 'HASSAN', 'ROSSI', 'TANAKA', 'BROWN',
        'IVANOVA', 'SILVA', 'MURPHY', 'COHEN', 'PATEL', 'JOHANSSON', 'DUBOIS', 'KIM', 'OBRIEN', 'LOPEZ']


def build_accounts(rng):
    accts, n = [], 4100012000
    def add(product, status, opened, balance, rate):
        nonlocal n
        n += rng.randint(7, 97)
        name = f'{rng.choice(LAST)}, {rng.choice(FIRST)}'
        accts.append(Acct(n, product, status, opened, name, balance, rate))
        return accts[-1]
    # Handcrafted planted-fact accounts.
    add('SV2', 'A', date(2014, 5, 2), '54.75', '0.02500')      # Feb accrual 0.105: half-even 0.10, half-up 0.11
    add('SV1', 'A', date(2003, 9, 15), '63.00', '0.02000')     # 30/360 Feb accrual 0.105 -> 0.10 vs 0.11
    add('SV1', 'A', date(1997, 3, 3), '250000.00', '0.03500')  # 30/360 vs actual/365 visible in cents
    add('SV1', 'A', date(1988, 12, 1), '98210.44', '0.02750')  # 19xx open date
    add('SV1', 'F', date(2001, 6, 20), '15000.00', '0.02000')  # frozen: no interest, rejects txns
    add('CHK', 'A', date(2019, 1, 8), '120.00', '0')           # repeated overdraft crossings
    add('CHK', 'C', date(2008, 2, 29), '0.00', '0')            # closed
    for _ in range(14):
        add('CHK', rng.choice('AAAAAAF'), date(rng.randint(1985, 2024), rng.randint(1, 12), rng.randint(1, 28)),
            str(Decimal(rng.randint(0, 900000)) / 100), '0')
    for _ in range(7):
        add('SV1', 'A', date(rng.randint(1975, 2008), rng.randint(1, 12), rng.randint(1, 28)),
            str(Decimal(rng.randint(10000, 9000000)) / 100), f'0.0{rng.randint(1500, 3999)}')
    for _ in range(7):
        add('SV2', rng.choice('AAAAAC'), date(rng.randint(2009, 2024), rng.randint(1, 12), rng.randint(1, 28)),
            str(Decimal(rng.randint(5000, 5000000)) / 100), f'0.0{rng.randint(1000, 4500)}')
    for _ in range(5):
        add('MMA', 'A', date(rng.randint(1992, 2024), rng.randint(1, 12), rng.randint(1, 28)),
            str(Decimal(rng.randint(250000, 25000000)) / 100), f'0.0{rng.randint(3000, 4999)}')
    for a in accts:
        a.last_act = max(a.opened, date(2025, 1, 31) - timedelta(days=rng.randint(0, 40)))
    return accts


def build_day(rng, d, accts, seq):
    """Arrival-ordered TXNIN for one day, including retries, NSF, overdrafts, frozen/closed and unknown accounts."""
    live = [a for a in accts[2:] if a.status == 'A']   # the two tie accounts stay untouched
    chk = [a for a in live if a.product == 'CHK']
    sav = [a for a in live if a.product != 'CHK']
    special = [a for a in accts if a.status != 'A']
    out = []
    def ref():
        return rng.choice(['MOB', 'WEB', 'ATM']) + f'{rng.randint(0, 10**12 - 1):012d}' if rng.random() < .75 else ''
    def tid():
        seq[0] += 1
        return f'T{d:%y%m%d}{seq[0]:05d}'
    for _ in range(rng.randint(8, 16)):
        kind = rng.random()
        if kind < .35:
            a = rng.choice(live); out.append(txn_record(tid(), a.number, 'DP', Decimal(rng.randint(500, 250000)) / 100, d, 0, ref()))
        elif kind < .60:
            a = rng.choice(chk); out.append(txn_record(tid(), a.number, 'WD', Decimal(rng.randint(1000, 90000)) / 100, d, 0, ref()))
        elif kind < .72:
            a = rng.choice(sav); out.append(txn_record(tid(), a.number, 'WD', Decimal(rng.randint(1000, 400000 if rng.random() < .7 else 3000000)) / 100, d, 0, ref()))
        elif kind < .88:
            a, b = rng.sample(live, 2); out.append(txn_record(tid(), a.number, 'XF', Decimal(rng.randint(1000, 150000)) / 100, d, b.number, ref()))
        elif kind < .93:
            a = rng.choice(special); out.append(txn_record(tid(), a.number, rng.choice(['DP', 'WD']), Decimal(rng.randint(1000, 50000)) / 100, d, 0, ref()))
        elif kind < .95:
            out.append(txn_record(tid(), 4100099999, 'DP', Decimal('10.00'), d, 0, ref()))
        else:   # savings transfer just over the balance -> NSF
            a = rng.choice(sav); out.append(txn_record(tid(), a.number, 'XF', a.balance + Decimal(rng.randint(100, 9999)) / 100, d, rng.choice(chk).number, ref()))
    # Channel retries: re-send an earlier same-day txn with a new TXN-ID and the same TXN-REF.
    with_ref = [r for r in out if r[50:70].strip()]
    for r in rng.sample(with_ref, min(len(with_ref), rng.choice([0, 1, 1, 2]))):
        out.insert(rng.randint(out.index(r) + 1, len(out)), tid().ljust(12) + r[12:])
    if d.day == 10:   # a retry that arrives the NEXT day is not a duplicate
        r = rng.choice(with_ref); out.append(('CARRY', r))
    if d.day in (5, 12, 19, 26):   # overdraft crossings on the planted CHK account
        out.append(txn_record(tid(), accts[5].number, 'WD', Decimal('150.00'), d, 0, ''))
        out.append(txn_record(tid(), accts[5].number, 'DP', Decimal('200.00'), d, 0, ''))
    return out


# ---------- batch ----------
def last_of_month(d):
    return d.day == calendar.monthrange(d.year, d.month)[1]


def days_to_accrue(product, d):
    if BASIS[product] == 365:
        return 1
    if d.day == 31:
        return 0
    if d.month == 2 and last_of_month(d):
        return 30 - d.day + 1
    return 1


def run_day(d, accts, txns, month):
    by_num = {a.number: a for a in accts}
    posted, rejects, seen_refs, bseq = [], [], set(), 0
    def batch_id():
        nonlocal bseq
        bseq += 1
        return f'B{julian(d)}{bseq:06d}'
    for r in txns:
        acct, typ, amount, ctr, ref = int(r[12:22]), r[22:24], Decimal(int(r[24:35])) / 100, int(r[40:50]), r[50:70].strip()
        def reject(code):
            rejects.append(r + code)
        if ref and ref in seen_refs:
            reject('DUP'); continue
        parties = [acct] + ([ctr] if typ == 'XF' else [])
        code = None
        for p in parties:
            a = by_num.get(p)
            code = 'NOA' if a is None else 'CLS' if a.status == 'C' else 'FRZ' if a.status == 'F' else None
            if code:
                break
        if code:
            reject(code); continue
        a = by_num[acct]
        if typ in ('WD', 'XF'):
            if a.product != 'CHK' and amount > a.balance:
                reject('NSF'); continue
            before = a.balance
            a.balance -= amount
            if a.product == 'CHK' and a.balance < 0 <= before:
                a.od_count += 1
            if typ == 'XF':
                by_num[ctr].balance += amount; by_num[ctr].last_act = d
        else:
            a.balance += amount
        a.last_act = d
        if ref:
            seen_refs.add(ref)
        posted.append(r)
    for a in accts:
        if a.status == 'A' and a.product in BASIS and a.balance > 0:
            days = days_to_accrue(a.product, d)
            a.accrued += (a.balance * a.rate * days / BASIS[a.product]).quantize(C6, rounding=ROUND_DOWN)
    stmt = None
    if last_of_month(d):
        for a in accts:
            month[a.number] = {'interest': Decimal('0'), 'fees': Decimal('0')}
            if a.accrued > 0:
                amt = a.accrued.quantize(C2, rounding=ROUND_HALF_EVEN)
                if amt > 0:
                    a.balance += amt; month[a.number]['interest'] = amt
                    posted.append(txn_record(batch_id(), a.number, 'IN', amt, d))
            a.accrued = Decimal('0')
        for a in accts:
            if a.product == 'CHK' and a.status in 'AF':
                if a.balance < MF_THRESHOLD:
                    a.balance -= MF_FEE; month[a.number]['fees'] += MF_FEE
                    posted.append(txn_record(batch_id(), a.number, 'MF', MF_FEE, d))
                if a.od_count:
                    fee = OD_FEE * a.od_count
                    a.balance -= fee; month[a.number]['fees'] += fee
                    posted.append(txn_record(batch_id(), a.number, 'OD', fee, d))
                a.od_count = 0
        stmt = []
        for a in sorted(accts, key=lambda x: x.number):
            m = month[a.number]
            line = (f'{a.number:010d} {a.product} {a.status} {edit(a.balance, "-ZZZ,ZZZ,ZZ9.99")} '
                    f'{edit(m["interest"], "ZZ,ZZ9.99")} {edit(m["fees"], "ZZ,ZZ9.99")}')
            stmt.append(line.ljust(120))
    return posted, rejects, stmt


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(l + '\n' for l in lines), encoding='ascii', newline='\n')


def generate(out):
    rng = random.Random(20251111)
    accts = build_accounts(rng)
    write(out / 'input' / 'ACCTMAST.DAT', [a.record() for a in accts])
    d, carry, month = START, [], {}
    while d <= END:
        seq = [0]
        raw = build_day(rng, d, accts, seq)
        txns = [r for r in raw if not isinstance(r, tuple)]
        for old in carry:   # yesterday's retry, same TXN-REF, new id and date
            seq[0] += 1
            txns.insert(0, f'T{d:%y%m%d}{seq[0]:05d}'.ljust(12) + old[12:35] + julian(d) + old[40:])
        carry = [r[1] for r in raw if isinstance(r, tuple)]
        tag = f'D{d:%y%m%d}'
        write(out / 'input' / f'CTLCARD.{tag}.DAT', [julian(d)])
        write(out / 'input' / f'TXNIN.{tag}.DAT', txns)
        posted, rejects, stmt = run_day(d, accts, txns, month)
        write(out / 'golden' / tag / 'POSTED.DAT', posted)
        write(out / 'golden' / tag / 'REJECTS.DAT', rejects)
        write(out / 'golden' / tag / 'ACCTMAST.DAT', [a.record() for a in accts])
        if stmt:
            write(out / 'golden' / f'STMT-{d:%Y%m}.TXT', stmt)
        d += timedelta(days=1)
    return accts


def self_check():
    """Prove the planted facts change observable output (else the golden master could not test them)."""
    tie = Decimal('0.105')
    assert tie.quantize(C2, ROUND_HALF_EVEN) != tie.quantize(C2, ROUND_HALF_UP)
    feb = sum(days_to_accrue('SV1', date(2025, 2, k)) for k in range(1, 29))
    mar = sum(days_to_accrue('SV1', date(2025, 3, k)) for k in range(1, 32))
    assert (feb, mar) == (30, 30), (feb, mar)
    assert from_julian('98123').year == 1998 and from_julian('05123').year == 2005
    print('self-check ok: tie', tie, '-> HE', tie.quantize(C2, ROUND_HALF_EVEN), 'HU', tie.quantize(C2, ROUND_HALF_UP),
          '| SV1 accrual days Feb/Mar', feb, mar)


if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else Path('out')
    accts = generate(target)
    if '--check' in sys.argv:
        self_check()
    print(f'wrote {len(accts)} accounts, {(END - START).days + 1} days to {target}')
