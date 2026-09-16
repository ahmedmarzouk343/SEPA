"""
kashif_config.py -- Global operational flags and shared paths.

Edit this file to control pipeline behavior. Restart the pipeline after
changing any flag for it to take effect (this module is read once at import
time by kashif_strategy.py; there is no live-reload mechanism, no UI, no
API endpoint, no webhook -- see feature-07-operational-safety-rules.md
Section 2.3, "What does NOT change").
"""

from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "minervini_sepa_v1_strategy_config.json"

KILL_SWITCH = False  # Set to True to halt all new entry evaluation immediately.
                     # Held positions will still receive exit checks (stop-loss,
                     # breakeven trigger, largest-decline flag) -- the kill switch
                     # only prevents NEW entries, it does not abandon existing
                     # positions. This is global by design (kashif-project-
                     # summary.md: "one global pause that halts all strategies
                     # immediately, independent of per-strategy logic") -- there
                     # is no per-strategy kill switch, and no automatic reset;
                     # flipping back to False requires a human edit to this file.
