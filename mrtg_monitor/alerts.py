"""Notifikasi Telegram / email untuk temuan baru.

Setiap link punya tiga jenis alert: near_limit, gap, idle.
Alert dikirim sekali saat kondisi mulai aktif; saat pulih dikirim
notifikasi pemulihan (jika notify_recovery: true).
"""
import json
import smtplib
import time
import urllib.request
from email.mime.text import MIMEText

LABELS = {
    "near_limit": "⚠️ MENDEKATI LIMIT",
    "gap": "🔴 GRAFIK PUTUS",
    "idle": "💤 TRAFIK NOL",
}
RECOVERY_LABELS = {
    "near_limit": "✅ Utilisasi kembali normal",
    "gap": "✅ Grafik kembali terisi",
    "idle": "✅ Trafik kembali terpakai",
}


def _fmt_ts(ts):
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _describe(status, alert_type):
    lid, cust = status["link_id"], status["customer"]
    bw = status["bandwidth_mbps"]
    if alert_type == "near_limit":
        return (
            f"{LABELS[alert_type]} — {lid} ({cust}): puncak "
            f"{status['peak_util_pct']}% dari {bw:g} Mbps, menyentuh ambang "
            f"{status['near_limit_hit_days']} hari berturut-turut"
        )
    if alert_type == "gap":
        return (
            f"{LABELS[alert_type]} — {lid} ({cust}): data MRTG berhenti "
            f"sejak {_fmt_ts(status['gap_since'])}"
        )
    return (
        f"{LABELS[alert_type]} — {lid} ({cust}): trafik < ambang selama "
        f"{status['idle_days']:g} hari, kemungkinan layanan tidak dipakai"
    )


def process_alerts(cfg, store, statuses):
    """Bandingkan kondisi sekarang dengan alert_state, kirim digest."""
    prev = store.alert_states()
    new_msgs, recovered_msgs = [], []

    for s in statuses:
        if not s["has_mrtg"]:
            continue
        active_now = {
            "near_limit": bool(s["near_limit"]),
            "gap": bool(s["gap_active"]),
            "idle": bool(s["idle_active"]),
        }
        for atype, active in active_now.items():
            was_active = bool(prev.get((s["link_id"], atype), {}).get("active"))
            if active and not was_active:
                since = s["gap_since"] if atype == "gap" else int(time.time())
                store.set_alert_state(s["link_id"], atype, True, since)
                # episode baru: tindak lanjut episode lama tidak berlaku lagi
                store.clear_followup(s["link_id"], atype)
                new_msgs.append(_describe(s, atype))
            elif not active and was_active:
                store.set_alert_state(s["link_id"], atype, False, None)
                recovered_msgs.append(
                    f"{RECOVERY_LABELS[atype]} — {s['link_id']} ({s['customer']})"
                )

    parts = []
    if new_msgs:
        parts.append("Temuan baru:\n" + "\n".join(new_msgs))
    if recovered_msgs and cfg["alerts"].get("notify_recovery", True):
        parts.append("Pulih:\n" + "\n".join(recovered_msgs))
    if not parts:
        return {"new": 0, "recovered": len(recovered_msgs), "sent": False}

    body = "MRTG Monitor — " + time.strftime("%Y-%m-%d %H:%M") + "\n\n"
    body += "\n\n".join(parts)
    sent = _send_all(cfg["alerts"], body)
    return {"new": len(new_msgs), "recovered": len(recovered_msgs), "sent": sent}


def _send_all(acfg, body):
    sent = False
    tg = acfg.get("telegram", {})
    if tg.get("enabled"):
        _send_telegram(tg, body)
        sent = True
    em = acfg.get("email", {})
    if em.get("enabled"):
        _send_email(em, body)
        sent = True
    if not sent:
        print("[alert] Tidak ada kanal alert aktif; pesan:\n" + body)
    return sent


def _send_telegram(tg, body):
    url = f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage"
    payload = json.dumps({"chat_id": tg["chat_id"], "text": body}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=15).read()


def _send_email(em, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "[MRTG Monitor] Alert jaringan"
    msg["From"] = em["from"]
    msg["To"] = ", ".join(em["to"])
    with smtplib.SMTP(em["smtp_host"], int(em.get("smtp_port", 587)), timeout=30) as s:
        if em.get("use_tls", True):
            s.starttls()
        if em.get("smtp_user"):
            s.login(em["smtp_user"], em["smtp_password"])
        s.sendmail(em["from"], em["to"], msg.as_string())
