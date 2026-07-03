import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from .alerts import process_alerts
from .analyzer import analyze_series
from .config import demo_config, load_config
from .inventory import load_inventory
from .rrd_reader import DemoReader, RRDReader, demo_inventory
from .store import Store


def _lookback_days(th):
    return max(th["zero_days"], th["near_limit_days"]) + 1


def run_analyze(cfg):
    demo = cfg.get("demo", False)
    inventory = demo_inventory() if demo else load_inventory(cfg)
    reader = DemoReader(cfg) if demo else RRDReader(cfg)
    store = Store(cfg["db_path"])
    th = cfg["thresholds"]
    unit = cfg["rrd"]["unit"]
    days = _lookback_days(th)

    def process_link(link):
        lid = link["link_id"]
        base = {
            "link_id": lid,
            "customer": link["customer"],
            "bandwidth_mbps": link["bandwidth_mbps"],
            "has_mrtg": 0,
            "last_data_ts": None,
            "peak_util_pct": None,
            "avg_util_pct": None,
            "near_limit": 0,
            "near_limit_hit_days": 0,
            "gap_active": 0,
            "gap_since": None,
            "idle_active": 0,
            "idle_days": 0.0,
            "error": None,
        }
        if reader.exists(lid):
            base["has_mrtg"] = 1
            try:
                series = reader.fetch(lid, days)
                res = analyze_series(series, link["bandwidth_mbps"], th, unit)
                for k, v in res.items():
                    base[k] = int(v) if isinstance(v, bool) else v
            except Exception as e:  # RRD rusak/tidak terbaca: catat, lanjut
                base["error"] = str(e)
                print(f"[warn] {lid}: {e}", file=sys.stderr)
        return base

    # paralel: fetch RRD (subprocess/I/O-bound) untuk puluhan ribu SID
    with ThreadPoolExecutor(max_workers=cfg.get("workers", 8)) as pool:
        rows = list(pool.map(process_link, inventory))

    store.replace_statuses(rows)

    # RRD yang ada di direktori tapi tidak ada di inventory
    known = {
        cfg["rrd"]["pattern"].format(link_id=r["link_id"]) for r in rows
    }
    store.replace_orphans([f for f in reader.list_all() if f not in known])

    alert_info = process_alerts(cfg, store, rows)

    summary = {
        "total": len(rows),
        "with_mrtg": sum(r["has_mrtg"] for r in rows),
        "near_limit": sum(r["near_limit"] for r in rows),
        "gap": sum(r["gap_active"] for r in rows),
        "idle": sum(r["idle_active"] for r in rows),
        "alerts_new": alert_info["new"],
    }
    store.record_run(summary)

    print(
        "Analisis selesai {}: total {total} link, ada MRTG {with_mrtg}, "
        "belum {belum}, near-limit {near_limit}, putus {gap}, "
        "idle {idle}, alert baru {alerts_new}".format(
            time.strftime("%Y-%m-%d %H:%M"),
            belum=summary["total"] - summary["with_mrtg"],
            **summary,
        )
    )


def run_serve(cfg):
    import os

    from .web import create_app

    app = create_app(cfg)
    port = int(os.environ.get("PORT", cfg["web"]["port"]))
    app.run(host=cfg["web"]["host"], port=port)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="mrtg-monitor",
        description="Monitoring coverage & anomali link berbasis MRTG",
    )
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument(
        "--demo", action="store_true",
        help="pakai data sintetis (tanpa server MRTG/database)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("analyze", help="jalankan analisis satu kali (untuk cron)")
    sub.add_parser("serve", help="jalankan dashboard web")
    args = p.parse_args(argv)

    cfg = demo_config() if args.demo else load_config(args.config)
    if args.cmd == "analyze":
        run_analyze(cfg)
    else:
        run_serve(cfg)


if __name__ == "__main__":
    main()
