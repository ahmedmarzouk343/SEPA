"""Experiment 3 entry switches (entry_mode, rank_by, fund_mode, early_path, RS floor 95).

Synthetic panels and fundamentals only: no price cache, no store. The last test
is a differential one: with default switches the module must behave exactly as
the experiment-2 module (commit 71ba071) on the same random inputs, through
prepare(), candidates(), allocate(), manage(), sizing and bundles.
"""
import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kashif_engine import panel as PANEL  # noqa: E402
from kashif_engine.markets import US  # noqa: E402
from kashif_engine.strategies.minervini_sepa_v1 import module as M  # noqa: E402
from kashif_engine.strategies.minervini_sepa_v1 import signals as SIG  # noqa: E402

CFG = json.load(open(ROOT / "minervini_sepa_v1_strategy_config.json"))
REF_COMMIT = "71ba071"          # experiment-2 module, before the experiment-3 switches


def strat(**p):
    return M.Strategy(CFG, p, US)


# ---------------------------------------------------------------- synthetic world
def world(seed=0, n_days=60, n_tick=12):
    """A panel dict, a long fundamentals table and a VCP stand-in, all random but
    deterministic. Days are 2023 business days (outside every locked window)."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2023-02-01", periods=n_days)
    tick = [f"T{i:02d}" for i in range(n_tick)]
    wide = lambda a: pd.DataFrame(a, index=days, columns=tick)  # noqa: E731
    close = wide(100 * np.exp(np.cumsum(rng.normal(0.002, 0.02, (n_days, n_tick)), axis=0)))
    w = {
        "Close": close,
        "tt_core": wide(rng.random((n_days, n_tick)) < 0.5),
        "tt_early": wide(rng.random((n_days, n_tick)) < 0.7),
        "rs_pct": wide(rng.choice([50, 70, 80, 90, 94, 95, 97, 99, np.nan], (n_days, n_tick))),
        "vol_ratio": wide(rng.choice([0.8, 1.1, 1.2, 1.3, 1.5, 1.7, 2.5], (n_days, n_tick))),
        "atr14_pct": wide(rng.uniform(0.01, 0.05, (n_days, n_tick))),
        "high50_prev": wide(close.to_numpy() * rng.uniform(0.9, 1.1, (n_days, n_tick))),
        "sma_50": close * 0.95, "avgvol50": wide(np.full((n_days, n_tick), 1e6)),
        "addv50": wide(np.full((n_days, n_tick), 5e7)),
    }
    w["high50_prev"].iloc[:3, :2] = np.nan                     # young listings: no 50-day history
    w["regime"] = pd.DataFrame({"gate_open": rng.random(n_days) < 0.8,
                                "ratio_favorable": rng.random(n_days) < 0.6,
                                "pullback_shallow": rng.random(n_days) < 0.6,
                                "divergence": rng.random(n_days) < 0.6}, index=days)
    reasons = {"PASS": ["Q1=PASS, Q2=PASS, Q3=PASS, Q4=PASS", "Q1=PASS, Q2=SKIPPED, Q3=PASS, Q4=PASS"],
               "FAIL": ["Q1=PASS, Q2=FAIL, Q3=PASS, Q4=PASS", "Q1=PASS, Q2=PASS, Q3=PASS, Q4=FAIL",
                        "Q1=PASS, Q2=FAIL, Q3=PASS, Q4=FAIL", "Q1=PASS, Q2=PASS, Q3=FAIL, Q4=PASS",
                        "Q1 FAIL: EPS growth 5.0% < 20%", "Q1 FAIL: current EPS -0.1 is a loss",
                        "Q1=PASS, Q2=FAIL, Q3=SKIPPED, Q4=SKIPPED"],
               "SKIP": ["NO_FUNDAMENTALS", "STALE_130d"]}
    rows = []
    for d in days:
        for t in tick:
            v = rng.choice(["PASS", "FAIL", "SKIP"], p=[0.45, 0.4, 0.15])
            rows.append({"date": d, "ticker": t, "fund_verdict": v,
                         "fund_reason": reasons[v][rng.integers(len(reasons[v]))]})
    fund = pd.DataFrame(rows)
    return w, fund, days, tick


def fake_vcp(pre, vmin, workers=8, log=print):
    """Deterministic stand-in for SIG.vcp_table: same columns, price_ready by a hash."""
    out = []
    for t, d in zip(pre["ticker"], pre["date"]):
        h = (hash((t, str(d))) % 1000) / 1000
        out.append({"ticker": t, "date": d, "reason": "PRICE_READY" if h < 0.6 else "NO_BASE",
                    "price_ready_min": h < 0.6, "pivot": 90 + 20 * h, "vcp_quality": float(round(h * 3)),   # coarse: frequent ties
                    "volume_ratio": 1.2 + h, "close": 100.0})
    return pd.DataFrame(out, columns=["ticker", "date", "reason", "price_ready_min", "pivot", "vcp_quality",
                                      "volume_ratio", "close"])


@pytest.fixture
def patched(monkeypatch):
    calls = {"vcp_pre": []}
    state = {}

    def install(seed=0):
        w, fund, days, tick = world(seed)
        state.update(w=w, fund=fund, days=days, tick=tick)
        # Synthetic data: the bundle fingerprint must not read the LIVE price
        # cache and store, or a concurrent download that rewrites them flips
        # to_bundle/use_bundle into "built on other data" (it did, mid-run).
        from kashif_engine.data import fingerprint
        monkeypatch.setattr(fingerprint, "quick", lambda: {"synthetic": "test"})
        monkeypatch.setattr(PANEL, "load", lambda name="US": w)
        monkeypatch.setattr(SIG, "fundamentals_panel", lambda tickers, d, market, workers=8, log=print: fund)

        def vcp(pre, vmin, workers=8, log=print):
            calls["vcp_pre"].append(pre[["ticker", "date"]].astype(str).values.tolist())
            return fake_vcp(pre, vmin)
        monkeypatch.setattr(SIG, "vcp_table", vcp)
        return state
    return install, calls


def prepared(install, seed=0, **p):
    st = install(seed)
    s = strat(**p)
    s.prepare(st["tick"], st["days"][0], st["days"][-1], log=lambda *a: None)
    return s, st


# ---------------------------------------------------------------- params
def test_new_params_validate_and_rs_floor_95_is_allowed():
    s = strat()
    assert (s.p["entry_mode"], s.p["rank_by"], s.p["fund_mode"], s.p["early_path"]) == \
        ("vcp", "vcp_quality", "strict", False)
    assert strat(rs_threshold=95).p["rs_threshold"] == 95          # a stricter floor than the grid
    for bad in ({"entry_mode": "breakout"}, {"rank_by": "quality"}, {"fund_mode": "soft"},
                {"early_path": "yes"}, {"rs_threshold": 65}, {"rs_threshold": 101}):
        with pytest.raises(ValueError):
            strat(**bad)


# ---------------------------------------------------------------- fund_mode
@pytest.mark.parametrize("verdict,reason,expect", [
    ("FAIL", "Q1=PASS, Q2=FAIL, Q3=PASS, Q4=PASS", True),
    ("FAIL", "Q1=PASS, Q2=PASS, Q3=PASS, Q4=FAIL [BREAKOUT_YEAR]", True),
    ("FAIL", "Q1=PASS, Q2=FAIL, Q3=SKIPPED, Q4=SKIPPED", True),
    ("FAIL", "Q1=PASS, Q2=FAIL, Q3=PASS, Q4=FAIL", False),          # double fail
    ("FAIL", "Q1=PASS, Q2=PASS, Q3=FAIL, Q4=PASS", False),          # Q3 fail
    ("FAIL", "Q1 FAIL: EPS growth 5.0% < 20%", False),               # Q1 fail
    ("FAIL", "Q1 FAIL: current EPS -0.1 is a loss", False),          # loss override
    ("SKIP", "NO_FUNDAMENTALS", False),
    ("PASS", "Q1=PASS, Q2=PASS, Q3=PASS, Q4=PASS", False),          # a pass is not a soft pass
    ("FAIL", None, False),
])
def test_fund_soft_single_parser(verdict, reason, expect):
    assert M.fund_soft_single(verdict, reason) is expect


def test_soft_single_admits_single_q2_q4_fails_and_ranks_them_after_strict_passes(patched):
    install, _ = patched
    s, st = prepared(install, fund_mode="soft_single")
    fund = st["fund"].set_index(["date", "ticker"])
    assert s.vcp["fund_soft"].any() and (~s.vcp["fund_soft"]).any()
    for d, t, soft in zip(s.vcp["date"], s.vcp["ticker"], s.vcp["fund_soft"]):
        v, r = fund.loc[(d, t), ["fund_verdict", "fund_reason"]]
        assert (v == "PASS") != soft and (v == "PASS" or M.fund_soft_single(v, r))   # no veto ever admitted
    seen_mixed = False
    for day in st["days"]:
        c = s.candidates(None, day.date())
        flags = [x["fund_soft"] for x in c]
        assert flags == sorted(flags)                    # every strict pass before every soft pass
        seen_mixed |= (True in flags and False in flags)
    assert seen_mixed
    strict, _ = prepared(install)                        # the default admits no FAIL at all
    assert set(strict.vcp["ticker"] + strict.vcp["date"].astype(str)) <= \
        set(s.vcp["ticker"] + s.vcp["date"].astype(str))


# ---------------------------------------------------------------- early_path
def test_early_path_needs_rs_95_and_only_the_three_lines(patched):
    install, _ = patched
    s, st = prepared(install, early_path=True)
    w = st["w"]
    early_rows = s.vcp[s.vcp["trend_early"]]
    assert len(early_rows)
    for d, t in zip(early_rows["date"], early_rows["ticker"]):
        assert not w["tt_core"].at[d, t] and w["tt_early"].at[d, t] and w["rs_pct"].at[d, t] >= 95
    base, _ = prepared(install)
    added = set(zip(s.vcp["date"], s.vcp["ticker"])) - set(zip(base.vcp["date"], base.vcp["ticker"]))
    assert added == set(zip(early_rows["date"], early_rows["ticker"]))
    # an RS-94 name with the three lines but no full template is never a candidate
    st = install(0)
    st["w"]["rs_pct"].iloc[:, :] = 94.0
    st["w"]["tt_core"].iloc[:, :] = False
    st["w"]["tt_early"].iloc[:, :] = True
    s94 = strat(early_path=True)
    s94.prepare(st["tick"], st["days"][0], st["days"][-1], log=lambda *a: None)
    assert s94.vcp.empty


def test_panel_ticker_frame_adds_high50_prev_and_tt_early_and_changes_nothing_else():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2020-01-02", periods=320)
    c = pd.Series(50 * np.exp(np.cumsum(rng.normal(0.001, 0.02, len(idx)))), index=idx)
    df = pd.DataFrame({"Open": c * 0.99, "High": c * 1.01, "Low": c * 0.98, "Close": c,
                       "Volume": rng.integers(1e5, 1e6, len(idx)).astype(float)})
    f = PANEL.ticker_frame(df)
    exp_hi = pd.Series([c.iloc[i - 50:i].max() if i >= 50 else np.nan for i in range(len(c))], index=idx)
    pd.testing.assert_series_equal(f["high50_prev"], exp_hi, check_names=False)
    sma = {n: c.rolling(n).mean() for n in (50, 150, 200)}
    exp_early = (c > sma[150]) & (c > sma[200]) & (c > sma[50]) & sma[200].notna()
    assert f["tt_early"].equals(exp_early)
    assert not f["tt_early"].iloc[:199].any() and f["tt_early"].iloc[250:].any()
    old = _load_source("_panel_ref", _ref_source("kashif_engine/panel.py"), "kashif_engine/panel.py").ticker_frame(df)
    pd.testing.assert_frame_equal(f.drop(columns=["high50_prev", "tt_early"]), old)


# ---------------------------------------------------------------- entry_mode high50
def test_high50_replaces_only_the_vcp_gate_and_anchors_the_stop_at_the_prior_high(patched):
    install, calls = patched
    s, st = prepared(install, entry_mode="high50")
    assert not calls["vcp_pre"]                           # the VCP detector is not run at all
    w = st["w"]
    base, _ = prepared(install)
    assert calls["vcp_pre"]
    pre_pairs = {(t, pd.Timestamp(d)) for t, d in calls["vcp_pre"][-1]}   # the default pre-filter
    assert {(t, pd.Timestamp(d)) for t, d in zip(s.vcp["ticker"], s.vcp["date"])} == pre_pairs
    for r in s.vcp.itertuples():
        h, c = w["high50_prev"].at[r.date, r.ticker], w["Close"].at[r.date, r.ticker]
        assert r.price_ready_min == bool(h == h and c > h)
        assert r.volume_ratio == w["vol_ratio"].at[r.date, r.ticker]
        if r.price_ready_min:
            assert r.pivot == h
    day = next(d for d in st["days"] if s.candidates(None, d.date()))
    c = s.candidates(None, day.date())
    assert all(x["reason"] == "HIGH50_BREAKOUT" and x["volume_ratio"] >= s.p["breakout_volume"] for x in c)
    assert [x["rs_pct"] for x in c] == sorted((x["rs_pct"] for x in c), reverse=True)   # no VCP quality: RS order
    # stop anchor: 3% under the prior 50-day high, clamped to [4%, stop_max]
    st_ = {"entry_price": 100.0, "candidate": {"pivot": 98.0, "atr14_pct": 0.02, "pilot": False}}
    bar = NS(open=100, high=100, low=100, close=100, volume=1e6, sma50=float("nan"), avgvol50=1e6, atr14_pct=0.02)
    assert s.on_entry_filled(None, "X", st_, bar) == [("stop", pytest.approx(95.06), "STOP_LOSS")]


def test_high50_needs_the_new_panel_columns(patched, monkeypatch):
    install, _ = patched
    st = install(0)
    del st["w"]["high50_prev"]
    with pytest.raises(ValueError, match="high50_prev"):
        strat(entry_mode="high50").prepare(st["tick"], st["days"][0], st["days"][-1], log=lambda *a: None)


# ---------------------------------------------------------------- rank_by
def test_rank_by_rs_orders_by_rs_then_ticker(patched):
    install, _ = patched
    s, st = prepared(install, rank_by="rs")
    for day in st["days"]:
        c = s.candidates(None, day.date())
        assert [(-x["rs_pct"], x["ticker"]) for x in c] == sorted((-x["rs_pct"], x["ticker"]) for x in c)
    q, _ = prepared(install)
    multi = [d for d in st["days"] if len(q.candidates(None, d.date())) >= 2]
    assert multi
    for day in multi:
        c = q.candidates(None, day.date())
        assert [x["rank_score"] for x in c] == sorted((x["rank_score"] for x in c), reverse=True)


# ---------------------------------------------------------------- bundles
def test_bundle_records_the_entry_switches_and_refuses_others(patched, tmp_path):
    install, _ = patched
    s, _ = prepared(install, fund_mode="soft_single")
    path = tmp_path / "b.pkl"
    s.to_bundle(path)
    strat(fund_mode="soft_single").use_bundle(path)       # same switches: fine
    with pytest.raises(ValueError, match="built for"):
        strat().use_bundle(path)
    with pytest.raises(ValueError, match="built for"):
        strat(fund_mode="soft_single", early_path=True).use_bundle(path)
    d, _ = prepared(install)
    d.to_bundle(path)
    strat(rank_by="rs").use_bundle(path)                  # rank_by needs no other precomputation


# ---------------------------------------------------------------- differential: defaults == experiment 2
def _ref_source(rel):
    r = subprocess.run(["git", "show", f"{REF_COMMIT}:{rel}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"reference {REF_COMMIT}:{rel} not available: {r.stderr.strip()[:80]}")
    return r.stdout


def _load_source(name, src, rel):
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(ROOT / rel)          # module-level ROOT = Path(__file__).parents[...] must resolve
    exec(compile(src, f"<{name}>", "exec"), mod.__dict__)
    return mod


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_defaults_reproduce_experiment2_exactly(patched, tmp_path, seed):
    rel = "kashif_engine/strategies/minervini_sepa_v1/module.py"
    ref = _load_source("_module_ref", _ref_source(rel), rel)
    install, calls = patched
    st = install(seed)
    grid = [{}, {"rs_threshold": 90, "breakout_volume": 1.6}, {"rs_threshold": 80, "max_positions": 4},
            {"defensive_mode": "off", "regime_min_conditions": 2}, {"exit_mode": "run", "scaling": "config"}]
    for params in grid:
        new, old = M.Strategy(CFG, params, US), ref.Strategy(CFG, params, US)
        for s in (new, old):
            s.prepare(st["tick"], st["days"][0], st["days"][-1], log=lambda *a: None)
        assert calls["vcp_pre"][-1] == calls["vcp_pre"][-2]              # the same VCP work (cache key)
        pd.testing.assert_frame_equal(new.vcp, old.vcp)
        assert new.tickers_needed() == old.tickers_needed()
        assert {t: new.feed_start(t) for t in new.tickers_needed()} == \
            {t: old.feed_start(t) for t in old.tickers_needed()}
        # bundles: an experiment-2 bundle loads in the new module and vice versa
        pb_old, pb_new = tmp_path / f"o{seed}.pkl", tmp_path / f"n{seed}.pkl"
        old.to_bundle(pb_old)
        new.to_bundle(pb_new)
        M.Strategy(CFG, params, US).use_bundle(pb_old)
        ref.Strategy(CFG, params, US).use_bundle(pb_new)
        rng = random.Random(seed)
        for day in st["days"]:
            cn, co = new.candidates(None, day.date()), old.candidates(None, day.date())
            assert cn == co
            ctx = NS(n_open=rng.randint(0, 5), cash=rng.uniform(1e4, 1e5), pending_buy_value=rng.uniform(0, 1e4),
                     equity=1e5, addv={c["ticker"]: rng.choice([0.0, 1e6, 5e7]) for c in cn})
            an = new.allocate(ctx, [dict(c) for c in cn])
            ao = old.allocate(ctx, [dict(c) for c in co])
            assert an == ao
            for c, _ in an[:1]:                           # the full exit/sizing path on one fill
                _same_trade(new, old, c, rng)
        assert new.state_log == old.state_log and new.size_multiplier() == old.size_multiplier()


def _same_trade(new, old, cand, rng):
    entry = 100.0
    sn, so = {"entry_price": entry, "candidate": dict(cand)}, {"entry_price": entry, "candidate": dict(cand)}
    b = NS(open=entry, high=entry, low=entry, close=entry, volume=1e6, sma50=float("nan"), avgvol50=1e6,
           atr14_pct=0.02)
    assert new.on_entry_filled(None, "X", sn, b) == old.on_entry_filled(None, "X", so, b)
    sn["stop_price"] = so["stop_price"] = entry * (1 - sn["initial_stop_pct"])
    px = entry
    for i in range(1, 40):
        o = px * (1 + rng.gauss(0, 0.01))
        c = o * (1 + rng.gauss(0.003, 0.03))
        bar = NS(open=o, high=max(o, c) * 1.01, low=min(o, c) * 0.99, close=c, volume=rng.uniform(5e5, 3e6),
                 sma50=rng.choice([float("nan"), px * rng.uniform(0.8, 1.0)]), avgvol50=1e6, atr14_pct=0.02)
        sn["bars_held"] = so["bars_held"] = i
        an, ao = new.manage(None, "X", sn, bar), old.manage(None, "X", so, bar)
        assert an == ao and sn == so
        for a in an:
            if a[0] == "stop":
                sn["stop_price"] = so["stop_price"] = a[1]
        if an and an[0][0] == "exit":
            break
        px = c
    rec = {"net_pnl": rng.gauss(0, 100), "exit_date": "2023-01-01", "ticker": "X", "tag_pilot": rng.random() < 0.5}
    new.n_open += 1
    old.n_open += 1
    new.on_trade_closed(dict(rec))
    old.on_trade_closed(dict(rec))


def test_new_panel_columns_do_not_change_when_the_future_is_removed():
    """No lookahead: high50_prev and tt_early on day D depend only on bars up to D."""
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2019-01-02", periods=400)
    c = pd.Series(30 * np.exp(np.cumsum(rng.normal(0.001, 0.025, len(idx)))), index=idx)
    df = pd.DataFrame({"Open": c, "High": c * 1.02, "Low": c * 0.97, "Close": c,
                       "Volume": rng.integers(1e5, 1e6, len(idx)).astype(float)})
    full = PANEL.ticker_frame(df)[["high50_prev", "tt_early"]]
    for cut in (60, 201, 260, 399):
        part = PANEL.ticker_frame(df.iloc[:cut])[["high50_prev", "tt_early"]]
        pd.testing.assert_frame_equal(part, full.iloc[:cut])


def test_fund_score_counts_passed_questions_and_never_vetoes():
    from kashif_engine.strategies.minervini_sepa_v1.module import fund_score
    assert fund_score("PASS", "anything") == 4
    assert fund_score("FAIL", "Q1=PASS, Q2=FAIL, Q3=PASS, Q4=FAIL") == 2
    assert fund_score("FAIL", "Q1 FAIL: EPS growth 2.7% < 20%") == 0
    assert fund_score("SKIP", None) == 0
    from kashif_engine.strategies.minervini_sepa_v1.module import Strategy
    import json
    cfg = json.loads((ROOT / "minervini_sepa_v1_strategy_config.json").read_text(encoding="utf-8"))
    from kashif_engine.markets import US
    Strategy(cfg, {"fund_mode": "rank_only"}, US)          # accepted
    with pytest.raises(ValueError):
        Strategy(cfg, {"fund_mode": "loose"}, US)
