# MRTG Monitor

Monitoring coverage dan anomali link pelanggan berbasis data MRTG (RRD).

Menjawab empat pertanyaan operasional:

1. **Coverage** — dari total link di inventory, berapa yang sudah punya MRTG
   dan berapa yang belum, lengkap dengan kolom *alasan* yang bisa diisi tim.
2. **Mendekati limit** — link yang puncak utilisasi hariannya ≥ 80% dari BW
   kontrak selama 3 hari berturut-turut.
3. **Grafik putus** — link yang data MRTG-nya berhenti ≥ 6 jam
   (indikasi gangguan / perangkat mati / layanan diputus).
4. **Trafik nol** — link yang trafiknya terus di bawah 1% BW kontrak
   selama ≥ 14 hari (indikasi layanan tidak dipakai pelanggan).

Semua ambang bisa diubah di `config.yaml` tanpa menyentuh kode.

Setiap anomali (near-limit / putus / trafik nol) punya **status tindak
lanjut** (Belum ditangani / Sedang dicek / Pelanggan dihubungi / Tiket
dibuat / Selesai) plus catatan bebas, sehingga saat gangguan massal tim
tidak dobel mengecek SID yang sama. Status bisa difilter, dan otomatis
di-reset bila anomali yang sama muncul kembali sebagai kejadian baru.

## Coba dulu (mode demo, tanpa server MRTG)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m mrtg_monitor --demo analyze   # analisis data sintetis
.venv/bin/python -m mrtg_monitor --demo serve     # dashboard di :8080
```

## Pemakaian produksi

1. **Salin konfigurasi**: `cp config.example.yaml config.yaml`, lalu isi:
   - `rrd.dir` — direktori file `.rrd` MRTG (butuh `rrdtool` terpasang di
     server yang menjalankan tool ini).
   - `rrd.pattern` — pola nama file per link, mis. `"{link_id}.rrd"`.
     `{link_id}` diganti dengan ID link dari inventory, jadi penamaan file
     RRD harus konsisten dengan ID di inventory.
   - `inventory` — sumber daftar induk link (`mysql`/`postgres`/`csv`).
     Query SQL wajib mengembalikan kolom `link_id`, `customer`,
     `bandwidth_mbps`. Untuk MySQL pasang `pymysql`, untuk PostgreSQL
     `psycopg2-binary` (lihat `requirements.txt`).
   - `alerts` — aktifkan Telegram (bot token + chat id) dan/atau email SMTP.

2. **Jadwalkan analisis** via cron, misalnya tiap 15 menit:

   ```cron
   */15 * * * * cd /opt/mrtg-monitor && .venv/bin/python -m mrtg_monitor analyze >> analyze.log 2>&1
   ```

3. **Jalankan dashboard** (systemd/supervisor/screen):

   ```bash
   .venv/bin/python -m mrtg_monitor serve
   ```

   Untuk produksi sebaiknya di belakang gunicorn + nginx:
   `gunicorn 'mrtg_monitor.web:create_app(...)'` atau cukup Flask built-in
   untuk pemakaian internal tim.

## Cara kerja

- `analyze` membaca inventory, mencari file RRD tiap link
  (`rrd.pattern`), mengambil ±15 hari data via `rrdtool fetch`, menghitung
  status per link, menyimpannya ke SQLite (`db_path`), lalu mengirim alert
  hanya untuk kondisi yang **baru** aktif (dan notifikasi pemulihan saat
  normal kembali) — tidak ada spam alert berulang.
- Dashboard web hanya membaca SQLite, jadi ringan dan aman dijalankan
  terpisah dari proses analisis.
- File RRD yang ada di direktori tapi tidak cocok dengan inventory
  ditampilkan sebagai "RRD tanpa inventory" (kemungkinan layanan lama yang
  sudah dicabut).

## Catatan deteksi

- Utilisasi dihitung dari arah trafik tertinggi (in/out) per sampel;
  MRTG default menyimpan bytes/detik sehingga dikonversi ke bit (atur
  `rrd.unit` bila RRD Anda sudah dalam bit).
- "Mendekati limit" memakai puncak per hari kalender; link yang sedang
  putus tidak ikut dihitung near-limit/idle.
- "Trafik nol" dihitung mundur dari data valid terakhir, jadi jeda data
  (NaN) tidak dianggap trafik nol.
