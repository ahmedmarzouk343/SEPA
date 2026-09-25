"""Global kill switch. Halts NEW entries; held positions keep their exits.

Trips on any of:
  * the file kashif_data/KILL_SWITCH existing (manual, read every bar),
  * the environment variable KASHIF_KILL_SWITCH=1,
  * the legacy kashif_config.KILL_SWITCH flag,
  * an internal integrity failure (ledger drift, cost mismatch) -- these also
    raise, because a run whose books disagree must not produce a report.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLAG_FILE = ROOT / "kashif_data" / "KILL_SWITCH"


class KillSwitch:
    def __init__(self, run_id=None):
        self.run_id = run_id
        self.tripped_reason = None
        self.tripped_on = None
        self.halted_days = 0

    def trip(self, reason, when=None):
        if self.tripped_reason is None:
            self.tripped_reason, self.tripped_on = reason, str(when) if when else None

    def check(self, day):
        """(halted, reason) for new entries on `day`."""
        reason = self.tripped_reason
        if reason is None and FLAG_FILE.exists():
            reason = f"flag file {FLAG_FILE.name} present"
        if reason is None and os.environ.get("KASHIF_KILL_SWITCH", "").strip() in ("1", "true", "yes"):
            reason = "env KASHIF_KILL_SWITCH"
        if reason is None:
            try:
                import kashif_config
                if getattr(kashif_config, "KILL_SWITCH", False):
                    reason = "kashif_config.KILL_SWITCH"
            except Exception:  # noqa: BLE001 -- the legacy flag is optional
                pass
        if reason:
            self.halted_days += 1
            return True, reason
        return False, None

    def state(self):
        return {"tripped_reason": self.tripped_reason, "tripped_on": self.tripped_on,
                "halted_days": self.halted_days}
