"""Membaca data trafik dari file RRD MRTG via `rrdtool fetch`.

fetch() mengembalikan list (timestamp, in_value, out_value) dalam satuan
asli RRD (bytes/detik untuk MRTG default). Nilai None berarti tidak ada
data (NaN) pada slot waktu tersebut.
"""
import math
import os
import subprocess
import time


class RRDReader:
    def __init__(self, cfg):
        self.dir = cfg["rrd"]["dir"]
        self.pattern = cfg["rrd"]["pattern"]
        self.ds_in = cfg["rrd"]["ds_in"]
        self.ds_out = cfg["rrd"]["ds_out"]

    def rrd_path(self, link_id):
        return os.path.join(self.dir, self.pattern.format(link_id=link_id))

    def exists(self, link_id):
        return os.path.exists(self.rrd_path(link_id))

    def list_all(self):
        """Semua file .rrd di direktori (untuk deteksi RRD tanpa inventory)."""
        try:
            return sorted(
                f for f in os.listdir(self.dir) if f.endswith(".rrd")
            )
        except FileNotFoundError:
            return []

    def fetch(self, link_id, days):
        path = self.rrd_path(link_id)
        out = subprocess.run(
            ["rrdtool", "fetch", path, "AVERAGE", "-s", f"-{int(days)}d"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        lines = [l for l in out.splitlines() if l.strip()]
        if not lines:
            return []
        header = lines[0].split()
        try:
            idx_in = header.index(self.ds_in)
            idx_out = header.index(self.ds_out)
        except ValueError:
            raise ValueError(
                f"Data source {self.ds_in}/{self.ds_out} tidak ada di {path}; "
                f"yang tersedia: {header}"
            )
        series = []
        for line in lines[1:]:
            ts_part, _, vals_part = line.partition(":")
            if not vals_part:
                continue
            vals = vals_part.split()
            series.append(
                (
                    int(ts_part),
                    _num(vals[idx_in]) if idx_in < len(vals) else None,
                    _num(vals[idx_out]) if idx_out < len(vals) else None,
                )
            )
        return series


def _num(s):
    v = float(s)
    return None if math.isnan(v) else v


# --------------------------------------------------------------------------
# Mode demo: data sintetis supaya dashboard bisa dicoba tanpa server MRTG.
# --------------------------------------------------------------------------

DEMO_PROFILES = {
    "LNK-003": "busy",
    "LNK-011": "busy",
    "LNK-007": "gap",
    "LNK-009": "idle",
    "LNK-015": "idle",
    # LNK-018..020 sengaja tidak punya RRD (belum ada MRTG)
    "LNK-018": "missing",
    "LNK-019": "missing",
    "LNK-020": "missing",
}


def demo_inventory():
    customers = [
        "PT Maju Bersama", "Bank Nusantara", "RS Sehat Sentosa",
        "Universitas Cendekia", "PT Logistik Cepat", "Hotel Purnama",
        "PT Tambang Utama", "Pemda Kab. Sukamaju", "PT Retail Jaya",
        "CV Karya Mandiri", "PT Media Kreatif", "Sekolah Harapan",
        "PT Agro Lestari", "Klinik Medika", "PT Konstruksi Prima",
        "Koperasi Sejahtera", "PT Energi Baru", "PT Trans Angkasa",
        "Yayasan Pelita", "PT Digital Solusi",
    ]
    bws = [100, 50, 20, 200, 50, 30, 100, 50, 20, 10,
           50, 20, 30, 10, 50, 10, 100, 50, 20, 100]
    return [
        {
            "link_id": f"LNK-{i:03d}",
            "customer": customers[i - 1],
            "bandwidth_mbps": float(bws[i - 1]),
        }
        for i in range(1, 21)
    ]


class DemoReader:
    """Meniru RRDReader dengan data sintetis (satuan bytes/detik)."""

    STEP = 300

    def __init__(self, cfg):
        self.inventory = {r["link_id"]: r for r in demo_inventory()}

    def rrd_path(self, link_id):
        return f"(demo) {link_id}.rrd"

    def exists(self, link_id):
        return (
            link_id in self.inventory
            and DEMO_PROFILES.get(link_id) != "missing"
        )

    def list_all(self):
        rrds = [
            f"{lid}.rrd" for lid in self.inventory if self.exists(lid)
        ]
        return sorted(rrds + ["OLD-CIRCUIT-99.rrd"])  # contoh RRD yatim

    def fetch(self, link_id, days):
        import random

        rnd = random.Random(link_id)  # deterministik per link
        profile = DEMO_PROFILES.get(link_id, "normal")
        bw_bytes = self.inventory[link_id]["bandwidth_mbps"] * 1e6 / 8
        now = int(time.time()) // self.STEP * self.STEP
        start = now - int(days) * 86400
        series = []
        for ts in range(start, now + 1, self.STEP):
            if profile == "gap" and ts > now - 11 * 3600:
                series.append((ts, None, None))
                continue
            hour = time.localtime(ts).tm_hour + time.localtime(ts).tm_min / 60
            # pola harian: puncak sekitar jam 20:00
            daily = 0.5 + 0.5 * math.cos((hour - 20) / 24 * 2 * math.pi)
            if profile == "busy":
                level = (0.55 + 0.4 * daily) * bw_bytes
            elif profile == "idle":
                level = 0.001 * bw_bytes
            else:
                level = (0.15 + 0.35 * daily) * bw_bytes
            noise = 1 + rnd.uniform(-0.08, 0.08)
            down = level * noise
            up = down * rnd.uniform(0.2, 0.5)
            series.append((ts, round(down, 1), round(up, 1)))
        return series
