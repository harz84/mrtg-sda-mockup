"""Memuat daftar induk link pelanggan beserta BW kontrak.

Setiap baris inventory adalah dict dengan kunci minimal:
  link_id, customer, bandwidth_mbps
"""
import csv

REQUIRED = ("link_id", "customer", "bandwidth_mbps")


def _validate(rows):
    out = []
    for i, row in enumerate(rows, 1):
        missing = [c for c in REQUIRED if row.get(c) in (None, "")]
        if missing:
            raise ValueError(
                f"Baris inventory ke-{i} tidak punya kolom {missing}: {row}"
            )
        row["link_id"] = str(row["link_id"]).strip()
        row["customer"] = str(row["customer"]).strip()
        row["bandwidth_mbps"] = float(row["bandwidth_mbps"])
        out.append(row)
    return out


def _from_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _from_sql(sqlcfg, driver):
    query = sqlcfg.get("query")
    if not query:
        raise ValueError("inventory.sql.query belum diisi di config")
    if driver == "mysql":
        import pymysql

        conn = pymysql.connect(
            host=sqlcfg.get("host", "127.0.0.1"),
            port=int(sqlcfg.get("port", 3306)),
            user=sqlcfg.get("user"),
            password=sqlcfg.get("password", ""),
            database=sqlcfg.get("database"),
        )
    else:  # postgres
        import psycopg2

        conn = psycopg2.connect(
            host=sqlcfg.get("host", "127.0.0.1"),
            port=int(sqlcfg.get("port", 5432)),
            user=sqlcfg.get("user"),
            password=sqlcfg.get("password", ""),
            dbname=sqlcfg.get("database"),
        )
    try:
        cur = conn.cursor()
        cur.execute(query)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


def load_inventory(cfg):
    inv = cfg["inventory"]
    source = inv.get("source", "csv")
    if source == "csv":
        rows = _from_csv(inv["csv_path"])
    elif source in ("mysql", "postgres"):
        rows = _from_sql(inv.get("sql", {}), source)
    else:
        raise ValueError(f"inventory.source tidak dikenal: {source}")
    return _validate(rows)
