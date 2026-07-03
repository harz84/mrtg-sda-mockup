"""Dashboard web Flask: ringkasan, coverage, near-limit, putus, idle.

Pencarian, sorting, dan paginasi dilakukan di sisi server (SQLite),
sehingga tetap ringan meskipun jumlah SID mencapai puluhan ribu.
"""
import math
import os
import time
from urllib.parse import urlencode

from flask import Flask, redirect, render_template, request, url_for

from .store import Store

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")

PAGE_SIZE = 50

TAB_WHERE = {
    "coverage": "has_mrtg = 0",
    "nearlimit": "near_limit = 1",
    "putus": "gap_active = 1",
    "idle": "idle_active = 1",
}
DEFAULT_SORT = {
    "nearlimit": ("peak_util_pct", "desc"),
    "putus": ("gap_since", "asc"),
    "idle": ("idle_days", "desc"),
}
# jenis alert per tab anomali (untuk status tindak lanjut)
TAB_ALERT_TYPE = {
    "nearlimit": "near_limit",
    "putus": "gap",
    "idle": "idle",
}
FU_OPTIONS = [
    ("", "Belum ditangani"),
    ("dicek", "Sedang dicek"),
    ("dihubungi", "Pelanggan dihubungi"),
    ("tiket", "Tiket dibuat"),
    ("selesai", "Selesai"),
]
FU_VALUES = {v for v, _ in FU_OPTIONS}


def create_app(cfg):
    app = Flask(__name__, template_folder=os.path.abspath(TEMPLATE_DIR))

    def get_store():
        return Store(cfg["db_path"])

    @app.template_filter("ts")
    def fmt_ts(ts):
        if not ts:
            return "-"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))

    @app.template_filter("ago")
    def fmt_ago(ts):
        if not ts:
            return "-"
        secs = int(time.time() - ts)
        if secs < 3600:
            return f"{secs // 60} menit lalu"
        if secs < 86400:
            return f"{secs // 3600} jam lalu"
        return f"{secs / 86400:.1f} hari lalu"

    @app.context_processor
    def helpers():
        def qs(**overrides):
            """Query string saat ini + perubahan; page direset kecuali
            eksplisit di-set (mis. saat pindah sort/tab/pencarian)."""
            args = {k: request.args.get(k) for k in request.args}
            if "page" not in overrides:
                args.pop("page", None)
            args.update(overrides)
            args = {k: v for k, v in args.items() if v not in (None, "")}
            return "?" + urlencode(args)

        return dict(qs=qs)

    @app.route("/")
    def dashboard():
        store = get_store()
        tab = request.args.get("tab", "ringkasan")
        if tab not in TAB_WHERE and tab != "ringkasan":
            tab = "ringkasan"
        sid_q = request.args.get("sid", "").strip()
        cust_q = request.args.get("cust", "").strip()
        def_sort, def_dir = DEFAULT_SORT.get(tab, ("link_id", "asc"))
        sort = request.args.get("sort", def_sort)
        if sort not in Store.SORTABLE:
            sort = def_sort
        direction = request.args.get("dir", def_dir)
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1
        alert_type = TAB_ALERT_TYPE.get(tab)
        fu = request.args.get("fu", "")
        if fu not in FU_VALUES and fu != "belum":
            fu = ""

        rows, total_rows = store.query_statuses(
            tab_where=TAB_WHERE.get(tab),
            sid=sid_q,
            cust=cust_q,
            sort=sort,
            desc=(direction == "desc"),
            limit=PAGE_SIZE,
            offset=(page - 1) * PAGE_SIZE,
            alert_type=alert_type,
            fu=fu or None,
        )
        pages = max(1, math.ceil(total_rows / PAGE_SIZE))

        # jumlah anomali yang belum tersentuh sama sekali (untuk sorotan)
        fu_belum = 0
        if alert_type:
            _, fu_belum = store.query_statuses(
                tab_where=TAB_WHERE.get(tab),
                alert_type=alert_type,
                fu="belum",
                limit=1,
                offset=0,
            )

        orphans = store.orphans() if tab == "coverage" else []
        return render_template(
            "dashboard.html",
            tab=tab,
            sid_q=sid_q,
            cust_q=cust_q,
            sort=sort,
            dir=direction,
            page=page,
            pages=pages,
            total_rows=total_rows,
            rows=rows,
            alert_type=alert_type,
            fu=fu,
            fu_options=FU_OPTIONS,
            fu_belum=fu_belum,
            summary=store.summary(),
            top_util=store.top_util(10) if tab == "ringkasan" else [],
            reasons=store.reasons() if tab == "coverage" else {},
            orphans=orphans[:100],
            orphans_total=len(orphans),
            last_run=store.last_run(),
            thresholds=cfg["thresholds"],
        )

    @app.route("/reason", methods=["POST"])
    def save_reason():
        get_store().set_reason(
            request.form["link_id"], request.form.get("reason", "")
        )
        return redirect(
            request.referrer or url_for("dashboard", tab="coverage")
        )

    @app.route("/followup", methods=["POST"])
    def save_followup():
        alert_type = request.form["alert_type"]
        status = request.form.get("status", "")
        if (alert_type not in TAB_ALERT_TYPE.values()
                or status not in FU_VALUES):
            return redirect(request.referrer or url_for("dashboard"))
        get_store().set_followup(
            request.form["link_id"], alert_type,
            status, request.form.get("note", ""),
        )
        return redirect(request.referrer or url_for("dashboard"))

    return app
