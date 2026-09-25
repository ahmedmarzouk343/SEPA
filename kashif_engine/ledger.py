"""Double-entry ledger with T+N settlement. Virtual money only.

Every fill, dividend and settlement is a balanced journal entry in Decimal
(exact cents never drift across thousands of postings). Accounts:

  cash            settled cash
  receivable      sale proceeds awaiting settlement (T+N)
  payable         purchase cost awaiting settlement (T+N)
  securities      open positions at cost
  capital         starting virtual capital
  realized_pnl    gross gain/loss on shares sold (price only, before costs)
  commission      commission expense
  slippage        modelled slippage expense
  dividends       dividend income

reconcile() compares the ledger to the backtrader broker after every trade;
any drift beyond RECON_TOL raises LedgerDrift, which the engine turns into a
kill-switch halt -- a ledger that disagrees with the broker is a bug, not a
number to average away.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, getcontext

getcontext().prec = 34
D = lambda x: Decimal(repr(float(x)))  # noqa: E731 -- exact decimal of the float actually used
RECON_TOL = 1e-4                       # dollars, ledger (Decimal) vs broker (float)


class LedgerDrift(RuntimeError):
    pass


@dataclass
class Lot:
    shares: Decimal            # split-adjusted shares (the unit the broker holds)
    cost: Decimal              # total cost basis, price only


@dataclass
class Ledger:
    capital: float
    settlement_days: int
    balances: dict = field(default_factory=lambda: defaultdict(Decimal))
    journal: list = field(default_factory=list)
    lots: dict = field(default_factory=dict)          # ticker -> Lot
    pending: list = field(default_factory=list)       # (settle_index, account, amount)
    fills: list = field(default_factory=list)          # the trade list the auditor reads
    dividends_log: list = field(default_factory=list)

    def __post_init__(self):
        self._post(None, "capital contribution", [("cash", D(self.capital))], [("capital", D(self.capital))])

    # ------------------------------------------------------------------
    def _post(self, when, memo, debits, credits):
        dr = sum(a for _, a in debits)
        cr = sum(a for _, a in credits)
        if dr != cr:
            raise LedgerDrift(f"unbalanced entry {memo}: Dr {dr} != Cr {cr}")
        for acct, amt in debits:
            self.balances[acct] += amt
        for acct, amt in credits:
            self.balances[acct] -= amt
        self.journal.append({"date": str(when) if when else None, "memo": memo,
                             "debits": [(a, str(x)) for a, x in debits],
                             "credits": [(a, str(x)) for a, x in credits]})

    def settle(self, day_index: int, when):
        """Move every pending amount whose settlement day has arrived."""
        keep = []
        for idx, acct, amt in self.pending:
            if idx <= day_index:
                if acct == "receivable":
                    self._post(when, "settle sale", [("cash", amt)], [("receivable", amt)])
                else:
                    self._post(when, "settle purchase", [("payable", amt)], [("cash", amt)])
            else:
                keep.append((idx, acct, amt))
        self.pending = keep

    # ------------------------------------------------------------------
    def buy(self, when, day_index, ticker, shares, price, commission, slippage, raw_shares, raw_price, reason):
        q, p, c, s = D(shares), D(price), D(commission), D(slippage)
        gross = q * p
        total = gross + c + s
        self._post(when, f"buy {ticker}",
                   [("securities", gross), ("commission", c), ("slippage", s)], [("payable", total)])
        self.pending.append((day_index + self.settlement_days, "payable", total))
        lot = self.lots.get(ticker)
        if lot is not None:
            raise LedgerDrift(f"second buy on an open {ticker} lot -- strategy never adds to positions")
        self.lots[ticker] = Lot(q, gross)
        self.fills.append({"date": str(when), "ticker": ticker, "side": "BUY", "shares": float(shares),
                           "price": float(price), "commission": float(commission), "slippage": float(slippage),
                           "raw_shares": float(raw_shares), "raw_price": float(raw_price), "reason": reason})

    def sell(self, when, day_index, ticker, shares, price, commission, slippage, raw_shares, raw_price, reason):
        q, p, c, s = D(shares), D(price), D(commission), D(slippage)
        lot = self.lots.get(ticker)
        if lot is None or q > lot.shares:
            raise LedgerDrift(f"sell {shares} {ticker} exceeds ledger holding {lot.shares if lot else 0}")
        basis = lot.cost * q / lot.shares if q != lot.shares else lot.cost
        gross = q * p
        net = gross - c - s
        gain = gross - basis
        debits = [("receivable", net), ("commission", c), ("slippage", s)]
        credits = [("securities", basis)]
        if gain >= 0:
            credits.append(("realized_pnl", gain))
        else:
            debits.append(("realized_pnl", -gain))
        self._post(when, f"sell {ticker}", debits, credits)
        self.pending.append((day_index + self.settlement_days, "receivable", net))
        lot.shares -= q
        lot.cost -= basis
        if lot.shares == 0:
            del self.lots[ticker]
        self.fills.append({"date": str(when), "ticker": ticker, "side": "SELL", "shares": float(shares),
                           "price": float(price), "commission": float(commission), "slippage": float(slippage),
                           "raw_shares": float(raw_shares), "raw_price": float(raw_price), "reason": reason})

    def dividend(self, when, ticker, shares, per_share):
        amt = D(shares) * D(per_share)
        if amt == 0:
            return
        self._post(when, f"dividend {ticker}", [("cash", amt)], [("dividends", amt)])
        self.dividends_log.append({"date": str(when), "ticker": ticker, "shares": float(shares),
                                   "per_share": float(per_share), "amount": float(amt)})

    # ------------------------------------------------------------------
    def broker_cash(self) -> Decimal:
        """What backtrader shows as cash: it settles instantly, we do not.
        Balances are debit-positive, so a payable (a credit) is already negative."""
        b = self.balances
        return b["cash"] + b["receivable"] + b["payable"]

    def equity(self, marks: dict) -> Decimal:
        pos = sum(lot.shares * D(marks[t]) for t, lot in self.lots.items())
        return self.broker_cash() + pos

    def trial_balance_ok(self) -> bool:
        return sum(self.balances.values()) == 0

    def reconcile(self, broker, name_to_data, marks: dict, when):
        if not self.trial_balance_ok():
            raise LedgerDrift(f"{when}: trial balance does not sum to zero")
        bc = float(self.broker_cash())
        if abs(bc - broker.getcash()) > RECON_TOL:
            raise LedgerDrift(f"{when}: cash ledger {bc:.6f} vs broker {broker.getcash():.6f}")
        for t, lot in self.lots.items():
            size = broker.getposition(name_to_data[t]).size
            if abs(float(lot.shares) - size) > 1e-9:
                raise LedgerDrift(f"{when}: {t} ledger {lot.shares} shares vs broker {size}")
        for d in name_to_data.values():
            size = broker.getposition(d).size
            if size != 0 and d._name not in self.lots:
                raise LedgerDrift(f"{when}: broker holds {size} {d._name}, ledger holds none")
        eq = float(self.equity(marks))
        if abs(eq - broker.getvalue()) > max(RECON_TOL, 1e-9 * abs(eq)):
            raise LedgerDrift(f"{when}: equity ledger {eq:.6f} vs broker {broker.getvalue():.6f}")
        # Settlement invariant: settled cash never goes negative.
        if self.balances["cash"] < 0:
            raise LedgerDrift(f"{when}: settled cash negative ({self.balances['cash']})")
        return True

    def summary(self) -> dict:
        return {k: float(v) for k, v in self.balances.items()}
