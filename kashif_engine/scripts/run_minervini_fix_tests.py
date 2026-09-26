"""Test the engine fixes suggested by the Minervini comparison (frozen before any run).

    python kashif_engine/scripts/run_minervini_fix_tests.py 2022_2026
    python kashif_engine/scripts/run_minervini_fix_tests.py 2017_2021    # once, under its own pushed lock

Arms (the strategy config's own defaults otherwise -- nothing tuned):
  F0  S&P 400/600 universe, strict fundamentals        (the old engine, baseline)
  F1  S&P 1500 universe (adds current S&P 500 members), strict fundamentals
  F2  S&P 1500 universe, fundamentals rank_only (rank, never veto)
Per arm: raw returns; swept returns (idle cash held in MDY/IJR or in the
equal-weight member basket) against those benchmarks; and FAITHFULNESS -- how
many of Minervini's disclosed buys/holds (backtest_results/experiment3/
minervini_check/minervini_disclosed_trades.csv) the arm listed as a candidate
or bought within +-30 days of his date.
Honesty: the fixes were motivated by his 2021-2026 disclosures, universes are
CURRENT members (the S&P 500 part is survivorship-heavy: members are past
winners), and 2017-2021 has been used before. Results are diagnostic, not proof.
"""
import json
import os
import secrets
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import experiment2 as X2  # noqa: E402
from kashif_engine.data import prices as P  # noqa: E402
from kashif_engine.run_backtest import run_one  # noqa: E402
from kashif_engine.scripts.run_exp3_tests import evaluate, _git, _git_remote, REMOTE  # noqa: E402

OUT = ROOT / "kashif_data" / "minervini_fix"
RES = ROOT / "backtest_results" / "experiment3" / "minervini_check"
LOCK_REL = "kashif_data/minervini_fix/LOCK_2017_2021"
WINDOWS = {"2022_2026": ("2022-01-03", "2026-09-24"), "2017_2021": X2.VALIDATION}
ETF = {"XLE", "IBIT", "IWM", "IWN", "SPY", "DIA"}


def universe_1500():
    u = json.load(open(ROOT / "us_fundamentals" / "sp_universe.json"))
    cached = set(P.cached_tickers("US"))
    return sorted((set(u["sp400"]) | set(u["sp600"]) | set(u["sp500"])) & cached)


ARMS = {
    "F0": ({"panel": "US_idx"}, X2.index_universe),
    "F1": ({"panel": "US_1500"}, universe_1500),
    "F2": ({"panel": "US_1500", "fund_mode": "rank_only"}, universe_1500),
}


def faithfulness(run_dir: Path, start, end) -> dict:
    d = pd.read_csv(RES / "minervini_disclosed_trades.csv")
    d = d[d["action"].isin(["BUY", "HOLD"]) & ~d["ticker"].isin(ETF)].copy()
    d["when"] = pd.to_datetime(d["date_or_period"].astype(str).str.slice(0, 10).where(
        d["date_or_period"].astype(str).str.len() >= 10, d["date_or_period"].astype(str).str.slice(0, 7) + "-15"))
    d = d[(d["when"] >= start) & (d["when"] <= end)]
    c = pd.read_csv(run_dir / "candidates.csv", usecols=["ticker", "date"])
    c["date"] = pd.to_datetime(c["date"])
    t = pd.read_csv(run_dir / "trades.csv") if (run_dir / "trades.csv").exists() else pd.DataFrame(columns=["ticker", "entry_date"])
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    hit_c = hit_t = 0
    names = []
    for r in d.itertuples():
        near = lambda s: (s - r.when).abs() <= pd.Timedelta(days=30)  # noqa: E731
        hc = bool(((c["ticker"] == r.ticker) & near(c["date"])).any())
        ht = bool(((t["ticker"] == r.ticker) & near(t["entry_date"])).any())
        hit_c += hc
        hit_t += ht
        if hc:
            names.append(r.ticker)
    return {"his_buys_in_window": int(len(d)), "our_candidate_within_30d": hit_c, "our_trade_within_30d": hit_t,
            "matched": sorted(set(names))}


def run_window(key, token=None):
    from kashif_engine import panel as PANEL
    PANEL.build(universe_1500(), "US", name="US_1500", log=lambda *a: None)
    PANEL.build(X2.index_universe(), "US", name="US_idx", log=lambda *a: None)
    start, end = WINDOWS[key]
    res = {}
    for name, (params, uni) in ARMS.items():
        d = OUT / key / name
        run_one(start, end, params, run_id=f"MF_{name}_{key}", tickers=uni(), allow_validation2=token,
                out_dir=d, benchmarks=True)
        res[name] = evaluate(name, d, start, end) | {"faithfulness": faithfulness(d, start, end)}
    RES.mkdir(parents=True, exist_ok=True)
    (RES / f"FIX_TESTS_{key}.json").write_text(json.dumps(res, indent=2, default=str))
    return res


def main(key):
    if key == "2022_2026":
        res = run_window(key)
    else:
        lock = ROOT / LOCK_REL
        if lock.exists() or _git("log", "--all", "--oneline", "--", LOCK_REL).stdout.strip():
            sys.exit("REFUSED: this window was already claimed for these arms")
        lock.parent.mkdir(parents=True, exist_ok=True)
        nonce = secrets.token_hex(16)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w") as f:
            json.dump({"claimed_utc": datetime.now(timezone.utc).isoformat(), "nonce": nonce,
                       "arms": {k: v[0] for k, v in ARMS.items()},
                       "git_commit": _git("rev-parse", "HEAD").stdout.strip()}, f, indent=1)
        _git("add", "-f", LOCK_REL)
        if _git("-c", "commit.gpgsign=false", "commit", "--no-verify", "-m",
                "Minervini-fix tests: 2017-2021 claimed for F0-F2", "--", LOCK_REL).returncode != 0 \
                or _git_remote("push", "-q", REMOTE, "HEAD:main").returncode != 0:
            sys.exit("REFUSED: could not commit and push the claim")
        lk = json.loads(lock.read_text())
        try:
            res = run_window(key, nonce)
            lk["finished_utc"] = datetime.now(timezone.utc).isoformat()
        except BaseException as e:  # noqa: BLE001
            lk |= {"failed_utc": datetime.now(timezone.utc).isoformat(), "error": repr(e),
                   "traceback": traceback.format_exc()}
            raise
        finally:
            lock.write_text(json.dumps(lk, indent=1, default=str))
            _git("add", "-f", LOCK_REL)
            _git("-c", "commit.gpgsign=false", "commit", "--no-verify", "-m", "Minervini-fix tests: 2017-2021 lock closed",
                 "--", LOCK_REL)
            _git_remote("push", "-q", REMOTE, "HEAD:main")
    for k, v in res.items():
        f = v["faithfulness"]
        print(f"{k}: raw {v['raw']['total_return']:+.1%} ({v['raw']['cagr']:+.1%}/yr, Sharpe {v['raw']['sharpe']:.2f}, "
              f"DD {v['raw']['max_drawdown']:.1%}) trades {v['trades']} | swept->blend {v['swept_into_blend']['cagr']:+.1%} "
              f"vs blend {v['blend']['cagr']:+.1%} | his buys {f['his_buys_in_window']}: candidate {f['our_candidate_within_30d']}, "
              f"traded {f['our_trade_within_30d']} {f['matched']}")


if __name__ == "__main__":
    main(sys.argv[1])
