"""
Known-answer tests for the paired-experiment controls.

Two environment variables select the arm; the source is identical across both
runs. These tests exist because a silent default change here would invalidate
every comparison run afterwards without failing anything visible.
"""

import importlib
import os
from types import SimpleNamespace

import pytest


def _reload(env):
    """
    Re-import kashif_strategy with `env` applied and return a SNAPSHOT of the
    env-dependent constants, then restore the environment.

    A snapshot, not the module: importlib.reload() mutates the existing module
    object in place, so the restoring reload in `finally` would overwrite the
    very attributes the caller is about to assert on. `module` is exposed for
    the env-independent helpers (_stub_catalyst_result, the counter update),
    which are safe to reach through it.
    """
    keys = ("KASHIF_ENTRY_MARKET", "KASHIF_CATALYST_MODE")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ.pop(k, None)
        os.environ.update(env)
        import kashif_strategy
        mod = importlib.reload(kashif_strategy)
        return SimpleNamespace(
            ENTRY_TIMING_MARKET=mod.ENTRY_TIMING_MARKET,
            CATALYST_MODE=mod.CATALYST_MODE,
            CATALYST_STUBBED=mod.CATALYST_STUBBED,
            module=mod,
            _stub_catalyst_result=mod._stub_catalyst_result,
            KashifStrategy=mod.KashifStrategy,
        )
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import kashif_strategy
        importlib.reload(kashif_strategy)


def test_f1_defaults_are_production_behaviour():
    """
    PREDICTION: with nothing set, entry timing runs with market=None and
    catalyst is live.

    [UPDATED 2026-09-05] This fixture previously asserted market == "EGX".
    The paired test (Run A market=None +107.32%, 52.6% win rate vs Run B
    market="EGX" +42.11%, 30.2%) showed that default was harmful, so it was
    reverted to None. The assertion is updated to the new default rather than
    deleted, because its job is unchanged: catch a silent default flip, which
    would invalidate every comparison run afterwards.
    """
    m = _reload({})
    assert m.ENTRY_TIMING_MARKET is None
    assert m.CATALYST_MODE == "live"
    assert m.CATALYST_STUBBED is False


def test_f2_run_a_baseline():
    """PREDICTION: Run A is market=None (pre-Fix-1) with catalyst stubbed."""
    m = _reload({"KASHIF_ENTRY_MARKET": "NONE", "KASHIF_CATALYST_MODE": "stub"})
    assert m.ENTRY_TIMING_MARKET is None
    assert m.CATALYST_STUBBED is True


def test_f3_run_b_test_arm():
    """PREDICTION: Run B is market="EGX" (Fix 1 on) with catalyst stubbed."""
    m = _reload({"KASHIF_ENTRY_MARKET": "EGX", "KASHIF_CATALYST_MODE": "stub"})
    assert m.ENTRY_TIMING_MARKET == "EGX"
    assert m.CATALYST_STUBBED is True


def test_f3b_arms_differ_in_exactly_one_setting():
    """
    PREDICTION: the two arms agree on catalyst state and disagree only on
    ENTRY_TIMING_MARKET. This is the whole claim the comparison rests on.
    """
    a = _reload({"KASHIF_ENTRY_MARKET": "NONE", "KASHIF_CATALYST_MODE": "stub"})
    a_state = (a.CATALYST_MODE, a.CATALYST_STUBBED, a.ENTRY_TIMING_MARKET)
    b = _reload({"KASHIF_ENTRY_MARKET": "EGX", "KASHIF_CATALYST_MODE": "stub"})
    b_state = (b.CATALYST_MODE, b.CATALYST_STUBBED, b.ENTRY_TIMING_MARKET)
    assert a_state[:2] == b_state[:2]
    assert a_state[2] != b_state[2]


@pytest.mark.parametrize("raw", ["none", "NONE", "None", "null", " none ", ""])
def test_f4_none_spellings_all_mean_none(raw):
    """PREDICTION: the baseline arm cannot be missed by a casing or spacing slip."""
    assert _reload({"KASHIF_ENTRY_MARKET": raw}).ENTRY_TIMING_MARKET is None


def test_f5_stub_result_shape():
    """
    PREDICTION: the stub is NEUTRAL, non-blocking, counts no API call, and
    carries retry_log as an empty LIST — not None. A None there is what
    previously raised inside _update_catalyst_counters and, being swallowed by
    the caller's except, silently disabled catalyst_check for a whole run.
    """
    m = _reload({"KASHIF_CATALYST_MODE": "stub"})
    r = m._stub_catalyst_result("TEST")
    assert r["score"] == "NEUTRAL"
    assert r["pipeline_blocks_entry"] is False
    assert r["model_call_attempted"] is False
    assert r["error_flag"] is False
    assert r["retry_log"] == [] and isinstance(r["retry_log"], list)
    from catalyst_check import compute_pipeline_blocks_entry
    assert compute_pipeline_blocks_entry(r["score"]) is False


def test_f6_stub_leaves_every_ops_counter_at_zero():
    """
    PREDICTION: feeding the stub through the real counter update must move
    nothing — no API call, no error, no fallback-to-neutral. If any counter
    moved, the two arms' ops logs would differ for a reason unrelated to Fix 1.
    """
    m = _reload({"KASHIF_CATALYST_MODE": "stub"})
    strat = m.KashifStrategy.__new__(m.KashifStrategy)
    strat._catalyst_api_calls_made = 0
    strat._catalyst_api_errors = 0
    strat._catalyst_fallback_to_neutral = 0
    for tk in ("AAA", "BBB", "CCC"):
        strat._update_catalyst_counters(m._stub_catalyst_result(tk))
    assert (strat._catalyst_api_calls_made,
            strat._catalyst_api_errors,
            strat._catalyst_fallback_to_neutral) == (0, 0, 0)


def test_f7_run_label_scopes_every_output():
    """
    PREDICTION: with a label set, the receipts dir and the persistence store
    both carry the suffix, so two arms running at once cannot read or
    overwrite each other's state.
    """
    import run_backtest
    saved = os.environ.get("KASHIF_RUN_LABEL")
    try:
        os.environ["KASHIF_RUN_LABEL"] = "armX"
        rb = importlib.reload(run_backtest)
        assert rb.RUN_LABEL == "armX"
        assert rb._LABEL_SUFFIX == "_armX"
        assert rb.RECEIPTS_DIR.name == "decision_receipts_EGX_armX"

        os.environ.pop("KASHIF_RUN_LABEL")
        rb = importlib.reload(run_backtest)
        assert rb._LABEL_SUFFIX == ""
        assert rb.RECEIPTS_DIR.name == "decision_receipts_EGX"
    finally:
        if saved is None:
            os.environ.pop("KASHIF_RUN_LABEL", None)
        else:
            os.environ["KASHIF_RUN_LABEL"] = saved
        importlib.reload(run_backtest)
