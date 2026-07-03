import copy
import os

import yaml

DEFAULTS = {
    "rrd": {
        "dir": "/var/mrtg/rrd",
        "pattern": "{link_id}.rrd",
        "unit": "bytes",
        "ds_in": "ds0",
        "ds_out": "ds1",
    },
    "inventory": {
        "source": "csv",
        "csv_path": "inventory.csv",
        "sql": {},
    },
    "thresholds": {
        "near_limit_pct": 80,
        "near_limit_days": 3,
        "gap_hours": 6,
        "zero_pct": 1,
        "zero_days": 14,
    },
    "alerts": {
        "notify_recovery": True,
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "email": {"enabled": False},
    },
    "web": {"host": "0.0.0.0", "port": 8080},
    "db_path": "monitor.db",
    # jumlah thread paralel saat membaca RRD (naikkan bila SID puluhan ribu)
    "workers": 8,
}


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path):
    data = {}
    if path and os.path.exists(path):
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    return _merge(DEFAULTS, data)


def demo_config():
    """Konfigurasi mode demo: data sintetis, DB terpisah."""
    cfg = _merge(DEFAULTS, {})
    cfg["demo"] = True
    cfg["db_path"] = "demo.db"
    return cfg
