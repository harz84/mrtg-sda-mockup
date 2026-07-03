"""Analisis deret waktu MRTG per link.

Menghasilkan status per link:
  - gap_active / gap_since : grafik putus (tidak ada data valid)
  - near_limit             : utilisasi puncak harian >= ambang selama N hari
  - idle_active / idle_days: trafik nyaris nol berkepanjangan
  - peak_util_pct / avg_util_pct / last_data_ts
"""
import time
from collections import defaultdict


def _to_bps(value, unit):
    return value * 8 if unit == "bytes" else value


def analyze_series(series, bandwidth_mbps, thresholds, unit="bytes", now=None):
    now = now or time.time()
    cap_bps = bandwidth_mbps * 1e6
    th = thresholds

    result = {
        "last_data_ts": None,
        "peak_util_pct": None,
        "avg_util_pct": None,
        "gap_active": False,
        "gap_since": None,
        "near_limit": False,
        "near_limit_hit_days": 0,
        "idle_active": False,
        "idle_days": 0.0,
    }

    # sampel valid: minimal satu arah punya nilai; utilisasi = arah tertinggi
    valid = []
    for ts, v_in, v_out in series:
        vals = [v for v in (v_in, v_out) if v is not None]
        if not vals:
            continue
        util_pct = _to_bps(max(vals), unit) / cap_bps * 100
        valid.append((ts, util_pct))

    # --- grafik putus -----------------------------------------------------
    if not valid:
        result["gap_active"] = True
        result["gap_since"] = series[0][0] if series else None
        return result

    last_ts = valid[-1][0]
    result["last_data_ts"] = last_ts
    if now - last_ts >= th["gap_hours"] * 3600:
        result["gap_active"] = True
        result["gap_since"] = last_ts

    # --- utilisasi --------------------------------------------------------
    utils = [u for _, u in valid]
    result["peak_util_pct"] = round(max(utils), 1)
    result["avg_util_pct"] = round(sum(utils) / len(utils), 1)

    # --- mendekati limit BW kontrak ----------------------------------------
    # puncak per hari kalender; N hari terakhir yang ada datanya harus
    # semuanya menyentuh ambang.
    daily_peak = defaultdict(float)
    for ts, u in valid:
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        daily_peak[day] = max(daily_peak[day], u)
    recent_days = sorted(daily_peak)[-th["near_limit_days"]:]
    hits = sum(1 for d in recent_days if daily_peak[d] >= th["near_limit_pct"])
    result["near_limit_hit_days"] = hits
    result["near_limit"] = (
        len(recent_days) >= th["near_limit_days"]
        and hits == th["near_limit_days"]
        and not result["gap_active"]
    )

    # --- trafik nol / hampir nol -------------------------------------------
    # hitung mundur dari sampel valid terakhir: berapa lama trafik terus
    # berada di bawah zero_pct.
    if not result["gap_active"]:
        run_start = None
        for ts, u in reversed(valid):
            if u < th["zero_pct"]:
                run_start = ts
            else:
                break
        if run_start is not None:
            idle_secs = last_ts - run_start
            result["idle_days"] = round(idle_secs / 86400, 1)
            result["idle_active"] = idle_secs >= th["zero_days"] * 86400

    return result
