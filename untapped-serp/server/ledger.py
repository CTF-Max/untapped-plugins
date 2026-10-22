"""SQLite result cache + spend ledger with a daily cap (amounts in integer nanodollars)."""
import datetime as _dt
import json
import os
import sqlite3
import time
from pathlib import Path

from mcp_stdio import ToolError

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, tool TEXT, fetched_at REAL, result TEXT);
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY, ts REAL, day TEXT, tool TEXT, label TEXT,
  reserve_units INTEGER, cost_units INTEGER, status TEXT, cached INTEGER);
"""
# RESERVED = call in flight; COMPLETE = cost known; UNCERTAIN = may have been charged (reserve stays counted);
# REFUSED = blocked by the cap (never sent).
HELD = ("RESERVED", "UNCERTAIN")


def default_home():
    override = os.environ.get("UNTAPPED_SERP_HOME", "")
    if override and override != "${UNTAPPED_SERP_HOME}":
        return Path(override)
    # Not %LOCALAPPDATA%: Windows Store (MSIX) apps such as Claude desktop and Codex silently redirect new
    # AppData files into a per-app container, so each host would keep its own ledger, cap and sign-in.
    # The home folder is not virtualized, so every host and terminal shares one copy (found 2026-10-09).
    return Path.home() / ".untapped-plugins" / "serp"


def utc_day(ts=None):
    return _dt.datetime.fromtimestamp(ts if ts is not None else time.time(), _dt.timezone.utc).strftime("%Y-%m-%d")


class Ledger:
    def __init__(self, home=None, clock=time.time):
        self.home = Path(home) if home else default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "serp.sqlite3"
        self.clock = clock
        self.db = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        self.db.executescript(SCHEMA)

    # --- cache -------------------------------------------------------------------------------------
    def cached(self, key, max_age_hours):
        if max_age_hours <= 0:
            return None
        row = self.db.execute("SELECT fetched_at, result FROM cache WHERE key=?", (key,)).fetchone()
        if row and self.clock() - row[0] <= max_age_hours * 3600:
            return row[0], json.loads(row[1])
        return None

    def store(self, key, tool, result):
        self.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?,?)",
                        (key, tool, self.clock(), json.dumps(result, ensure_ascii=False)))

    # --- spend -------------------------------------------------------------------------------------
    def committed(self, day=None):
        """Charged cost plus reserves still held (in flight or uncertain) for one UTC day."""
        day = day or utc_day(self.clock())
        charged = self.db.execute("SELECT COALESCE(SUM(cost_units),0) FROM calls WHERE day=? AND status='COMPLETE'",
                                  (day,)).fetchone()[0]
        held = self.db.execute("SELECT COALESCE(SUM(reserve_units),0) FROM calls WHERE day=? AND status IN (?,?)",
                               (day,) + HELD).fetchone()[0]
        return charged, held

    def reserve(self, tool, label, reserve_units, cap_units):
        """Atomically check the cap and hold a reserve. Returns the call id; raises ToolError if refused."""
        now = self.clock()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            charged, held = self.committed(utc_day(now))
            if charged + held + reserve_units > cap_units:
                self.db.execute("INSERT INTO calls (ts,day,tool,label,reserve_units,cost_units,status,cached) "
                                "VALUES (?,?,?,?,?,NULL,'REFUSED',0)", (now, utc_day(now), tool, label, reserve_units))
                self.db.execute("COMMIT")
                raise ToolError(
                    "Daily cap reached: charged today $%.4f + held $%.4f + this call's reserve $%.4f > cap $%.2f. "
                    "Raise UNTAPPED_SERP_DAILY_CAP_USD or wait for the next UTC day."
                    % (charged / 1e9, held / 1e9, reserve_units / 1e9, cap_units / 1e9))
            cur = self.db.execute("INSERT INTO calls (ts,day,tool,label,reserve_units,cost_units,status,cached) "
                                  "VALUES (?,?,?,?,?,NULL,'RESERVED',0)", (now, utc_day(now), tool, label, reserve_units))
            self.db.execute("COMMIT")
            return cur.lastrowid
        except ToolError:
            raise
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def complete(self, call_id, cost_units):
        self.db.execute("UPDATE calls SET status='COMPLETE', cost_units=? WHERE id=?", (cost_units, call_id))

    def uncertain(self, call_id):
        self.db.execute("UPDATE calls SET status='UNCERTAIN' WHERE id=?", (call_id,))

    def cache_hit(self, tool, label):
        now = self.clock()
        self.db.execute("INSERT INTO calls (ts,day,tool,label,reserve_units,cost_units,status,cached) "
                        "VALUES (?,?,?,?,0,0,'COMPLETE',1)", (now, utc_day(now), tool, label))

    def summary(self):
        now = self.clock()
        day, month = utc_day(now), utc_day(now)[:7]
        charged, held = self.committed(day)
        month_cost = self.db.execute("SELECT COALESCE(SUM(cost_units),0) FROM calls WHERE substr(day,1,7)=? "
                                     "AND status='COMPLETE'", (month,)).fetchone()[0]
        hits = self.db.execute("SELECT COUNT(*) FROM calls WHERE cached=1").fetchone()[0]
        last = self.db.execute("SELECT ts,tool,label,cost_units,status,cached FROM calls ORDER BY id DESC LIMIT 10")
        return {
            "utc_day": day, "charged_today_usd": charged / 1e9, "held_uncertain_today_usd": held / 1e9,
            "charged_this_month_usd": month_cost / 1e9, "cache_hits_total": hits,
            "last_calls": [{"utc": _dt.datetime.fromtimestamp(r[0], _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "tool": r[1], "request": r[2], "cost_usd": None if r[3] is None else r[3] / 1e9,
                            "status": r[4], "cached": bool(r[5])} for r in last],
        }
