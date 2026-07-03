"""Penyimpanan SQLite: hasil analisis, alasan belum-MRTG, status alert."""
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS link_status (
    link_id        TEXT PRIMARY KEY,
    customer       TEXT,
    bandwidth_mbps REAL,
    has_mrtg       INTEGER,
    last_data_ts   INTEGER,
    peak_util_pct  REAL,
    avg_util_pct   REAL,
    near_limit     INTEGER,
    near_limit_hit_days INTEGER,
    gap_active     INTEGER,
    gap_since      INTEGER,
    idle_active    INTEGER,
    idle_days      REAL,
    error          TEXT,
    updated_at     INTEGER
);
CREATE TABLE IF NOT EXISTS reasons (
    link_id    TEXT PRIMARY KEY,
    reason     TEXT,
    updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS alert_state (
    link_id    TEXT,
    alert_type TEXT,
    active     INTEGER,
    since      INTEGER,
    last_sent  INTEGER,
    PRIMARY KEY (link_id, alert_type)
);
CREATE TABLE IF NOT EXISTS orphan_rrds (
    filename TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS followups (
    link_id    TEXT,
    alert_type TEXT,
    status     TEXT,
    note       TEXT,
    updated_at INTEGER,
    PRIMARY KEY (link_id, alert_type)
);
CREATE TABLE IF NOT EXISTS runs (
    ts      INTEGER,
    summary TEXT
);
"""


class Store:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # -- hasil analisis ----------------------------------------------------
    def replace_statuses(self, rows):
        now = int(time.time())
        with self.conn:
            self.conn.execute("DELETE FROM link_status")
            self.conn.executemany(
                """INSERT INTO link_status VALUES
                   (:link_id, :customer, :bandwidth_mbps, :has_mrtg,
                    :last_data_ts, :peak_util_pct, :avg_util_pct,
                    :near_limit, :near_limit_hit_days,
                    :gap_active, :gap_since, :idle_active, :idle_days,
                    :error, %d)""" % now,
                rows,
            )

    def statuses(self):
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM link_status ORDER BY link_id"
            )
        ]

    SORTABLE = {
        "link_id", "customer", "bandwidth_mbps", "has_mrtg",
        "peak_util_pct", "avg_util_pct", "last_data_ts",
        "gap_since", "idle_days", "near_limit_hit_days",
    }

    def query_statuses(self, tab_where=None, sid=None, cust=None,
                       sort="link_id", desc=False, limit=50, offset=0,
                       alert_type=None, fu=None):
        """Filter + sort + paginasi di sisi SQL, aman untuk puluhan ribu SID.

        alert_type (near_limit|gap|idle) ikut mengambil status tindak
        lanjut (fu_status/fu_note/fu_updated); fu memfilter berdasarkan
        status itu ('belum' = belum ditangani).
        """
        if sort not in self.SORTABLE:
            sort = "link_id"
        select, join, params = "SELECT ls.*", "", []
        if alert_type:
            select += (", f.status AS fu_status, f.note AS fu_note, "
                       "f.updated_at AS fu_updated")
            join = ("LEFT JOIN followups f ON f.link_id = ls.link_id "
                    "AND f.alert_type = ?")
            params.append(alert_type)
        clauses, wparams = [], []
        if tab_where:
            clauses.append(tab_where)
        if sid:
            clauses.append("ls.link_id LIKE ?")
            wparams.append(f"%{sid}%")
        if cust:
            clauses.append("ls.customer LIKE ?")
            wparams.append(f"%{cust}%")
        if fu and alert_type:
            if fu == "belum":
                clauses.append("(f.status IS NULL OR f.status = '')")
            else:
                clauses.append("f.status = ?")
                wparams.append(fu)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        total = self.conn.execute(
            f"SELECT COUNT(*) FROM link_status ls {join} {where}",
            params + wparams,
        ).fetchone()[0]
        rows = self.conn.execute(
            f"{select} FROM link_status ls {join} {where} "
            f"ORDER BY (ls.{sort} IS NULL), ls.{sort} "
            f"{'DESC' if desc else 'ASC'}, ls.link_id LIMIT ? OFFSET ?",
            params + wparams + [limit, offset],
        )
        return [dict(r) for r in rows], total

    # -- tindak lanjut anomali (per link + jenis alert) ----------------------
    def set_followup(self, link_id, alert_type, status, note):
        with self.conn:
            self.conn.execute(
                "INSERT INTO followups VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(link_id, alert_type) DO UPDATE SET "
                "status=excluded.status, note=excluded.note, "
                "updated_at=excluded.updated_at",
                (link_id, alert_type, status.strip(), note.strip(),
                 int(time.time())),
            )

    def clear_followup(self, link_id, alert_type):
        with self.conn:
            self.conn.execute(
                "DELETE FROM followups WHERE link_id = ? AND alert_type = ?",
                (link_id, alert_type),
            )

    def summary(self):
        r = self.conn.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(has_mrtg),0) AS with_mrtg, "
            "COALESCE(SUM(near_limit),0) AS near_limit, "
            "COALESCE(SUM(gap_active),0) AS gap, "
            "COALESCE(SUM(idle_active),0) AS idle "
            "FROM link_status"
        ).fetchone()
        s = dict(r)
        s["without_mrtg"] = s["total"] - s["with_mrtg"]
        s["normal"] = (
            s["with_mrtg"] - s["near_limit"] - s["gap"] - s["idle"]
        )
        return s

    def top_util(self, n=10):
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT link_id, customer, avg_util_pct FROM link_status "
                "WHERE avg_util_pct IS NOT NULL "
                "ORDER BY avg_util_pct DESC LIMIT ?",
                (n,),
            )
        ]

    def replace_orphans(self, filenames):
        with self.conn:
            self.conn.execute("DELETE FROM orphan_rrds")
            self.conn.executemany(
                "INSERT INTO orphan_rrds VALUES (?)",
                [(f,) for f in filenames],
            )

    def orphans(self):
        return [
            r["filename"]
            for r in self.conn.execute(
                "SELECT filename FROM orphan_rrds ORDER BY filename"
            )
        ]

    def record_run(self, summary):
        with self.conn:
            self.conn.execute(
                "INSERT INTO runs VALUES (?, ?)",
                (int(time.time()), json.dumps(summary)),
            )

    def last_run(self):
        row = self.conn.execute(
            "SELECT ts, summary FROM runs ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {"ts": row["ts"], **json.loads(row["summary"])}

    # -- alasan belum ada MRTG ----------------------------------------------
    def set_reason(self, link_id, reason):
        with self.conn:
            self.conn.execute(
                "INSERT INTO reasons VALUES (?, ?, ?) "
                "ON CONFLICT(link_id) DO UPDATE SET reason=excluded.reason, "
                "updated_at=excluded.updated_at",
                (link_id, reason.strip(), int(time.time())),
            )

    def reasons(self):
        return {
            r["link_id"]: r["reason"]
            for r in self.conn.execute("SELECT link_id, reason FROM reasons")
        }

    # -- status alert (untuk deduplikasi notifikasi) -------------------------
    def alert_states(self):
        return {
            (r["link_id"], r["alert_type"]): dict(r)
            for r in self.conn.execute("SELECT * FROM alert_state")
        }

    def set_alert_state(self, link_id, alert_type, active, since):
        with self.conn:
            self.conn.execute(
                "INSERT INTO alert_state VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(link_id, alert_type) DO UPDATE SET "
                "active=excluded.active, since=excluded.since, "
                "last_sent=excluded.last_sent",
                (link_id, alert_type, int(active), since, int(time.time())),
            )
