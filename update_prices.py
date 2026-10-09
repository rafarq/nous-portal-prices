#!/usr/bin/env python3
"""Pipeline diario de nous-portal-prices (usado por el cron).

Flujo:
  1. Regenera prices.json / prices_prev.json leyendo el catálogo oficial de
     Nous Portal (fetch_prices.py -> inference-api.nousresearch.com/v1/models).
     NO se usa OpenRouter ni la captura del portal web en ningún punto.
  2. Guarda el histórico SQL (history.db) y exporta history.json
  3. Despliega a media.rafarq.com/models (deploy.py)
  4. Imprime por stdout el mensaje de cambios SOLO si hay cambios de precio
     en los modelos anclados (pin.php remoto). stdout vacío = cron silencioso.

Uso:
    python3 update_prices.py
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "history.db"
HISTORY_JSON = BASE / "history.json"
PIN_URL = "https://media.rafarq.com/models/pin.php"
PCT_EPS = 2.0  # mínimo % de variación para considerarlo cambio


def change_pct(change: dict | None) -> float:
    """% de variación de un lado del cambio; 0 si no hay cambio, inf si old==0.

    `pct` es None cuando el precio anterior era 0 (no hay base para el %):
    como los precios nunca son negativos, eso es siempre una subida.
    """
    if not change:
        return 0.0
    p = change.get("pct")
    return float("inf") if p is None else float(p)


def run(cmd: list[str], timeout: int = 600) -> str:
    r = subprocess.run(cmd, cwd=str(BASE), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} falló (rc={r.returncode}): {r.stderr[-800:] or r.stdout[-800:]}")
    return r.stdout


def fetch_pins() -> list[str]:
    """IDs anclados desde el servidor (estado real)."""
    try:
        import urllib.request
        with urllib.request.urlopen(PIN_URL, timeout=30) as r:
            data = json.load(r)
        return [str(i) for i in (data.get("ids") or [])]
    except Exception as e:
        print(f"AVISO: no se pudieron leer los anclados ({e}); sin mensaje", file=sys.stderr)
        return []


def insert_history(doc: dict) -> None:
    """Guarda en SQLite los precios cuando hay cambios y exporta history.json.

    - Para cada modelo con change (respecto a prices_prev) inserta el punto
      ANTERIOR (old, ts_prev) y el NUEVO (new, ts_now) si no existen aún
      (PRIMARY KEY id+ts, INSERT OR IGNORE -> sin duplicados).
    - Los modelos sin cambio se siembran una sola vez como baseline (ts_now).
    """
    ts_now = doc.get("generated_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    # El valor anterior se fecha a las 12:00 del día ANTERIOR: es un marcador
    # sintético y debe quedar ANTES del valor nuevo (el pase de ~06:00 UTC de
    # hoy), o la serie se dibuja con el último tramo invertido.
    ts_prev = (datetime.fromisoformat(ts_now).astimezone(timezone.utc) - timedelta(days=1)
               ).replace(hour=12, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")

    con = sqlite3.connect(DB)
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS price_history(
            id TEXT NOT NULL, ts TEXT NOT NULL, "in" REAL NOT NULL, out REAL NOT NULL,
            PRIMARY KEY (id, ts))""")
        n_new = 0
        for m in doc["models"]:
            mid, new_in, new_out = m["id"], float(m["in"]), float(m["out"])
            ch = m.get("change") or {}
            cin, cout = ch.get("in"), ch.get("out")
            changed = False
            if cin and cin.get("old") is not None and abs(change_pct(cin)) >= PCT_EPS:
                cur = con.execute("SELECT 1 FROM price_history WHERE id=? AND ts=?",
                                  (mid, ts_prev)).fetchone()
                if not cur:
                    con.execute('INSERT OR IGNORE INTO price_history (id, ts, "in", out) VALUES (?,?,?,?)',
                                (mid, ts_prev, float(cin["old"]), new_out))
                    n_new += 1
                changed = True
            if cout and cout.get("old") is not None and abs(change_pct(cout)) >= PCT_EPS:
                cur = con.execute("SELECT 1 FROM price_history WHERE id=? AND ts=?",
                                  (mid, ts_prev)).fetchone()
                if not cur:
                    con.execute('INSERT OR IGNORE INTO price_history (id, ts, "in", out) VALUES (?,?,?,?)',
                                (mid, ts_prev, new_in, float(cout["old"])))
                    n_new += 1
                changed = True
            if changed:
                con.execute('INSERT OR IGNORE INTO price_history (id, ts, "in", out) VALUES (?,?,?,?)',
                            (mid, ts_now, new_in, new_out))
                n_new += 1
            else:
                # baseline: primera vez que vemos el modelo, sembrar una muestra
                cur = con.execute("SELECT 1 FROM price_history WHERE id=?", (mid,)).fetchone()
                if not cur:
                    con.execute('INSERT OR IGNORE INTO price_history (id, ts, "in", out) VALUES (?,?,?,?)',
                                (mid, ts_now, new_in, new_out))
                    n_new += 1
        con.commit()

        # exportar history.json: {id: [{ts, in, out}, ...]} asc por ts
        hist: dict[str, list[dict]] = {}
        for row in con.execute(
                'SELECT id, ts, "in", out FROM price_history ORDER BY ts ASC'):
            hist.setdefault(row[0], []).append({"ts": row[1], "in": row[2], "out": row[3]})
        HISTORY_JSON.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
        print(f"  histórico SQL: {n_new} filas nuevas | {len(hist)} modelos en history.json", file=sys.stderr)
    finally:
        con.close()


def pinned_changes_message(doc: dict) -> str:
    """Mensaje con los cambios de los anclados: modelo, anterior, flecha, nuevo."""
    pins = fetch_pins()
    if not pins:
        return ""
    models = {m["id"]: m for m in doc["models"]}
    lines = []
    for pid in pins:
        m = models.get(pid)
        if not m:
            continue
        ch = m.get("change") or {}
        parts = []
        for key, label in (("in", "in"), ("out", "out")):
            c = ch.get(key)
            if not c or c.get("old") is None:
                continue
            pct = change_pct(c)
            if abs(pct) < PCT_EPS:
                continue
            arrow = "🔺" if pct > 0 else "🔻"
            old = f"{float(c['old']):.4g}".rstrip("0").rstrip(".")
            new = f"{float(m[key]):.4g}".rstrip("0").rstrip(".")
            parts.append(f"{label} ${old} {arrow} ${new}")
        if parts:
            name = m.get("name") or pid
            up = any(change_pct(ch.get(k) or {}) > 0 for k in ("in", "out"))
            lines.append(f"{'🔺' if up else '🔻'} **{name}** (`{pid}`):\n   " + "\n   ".join(parts))
    if not lines:
        return ""
    today = datetime.now().strftime("%d/%m/%Y")
    return f"📊 Cambios de precio (anclados) — {today}:\n\n" + "\n".join(lines)


def main() -> int:
    log = open(BASE / "update.log", "a", encoding="utf-8")
    def logln(s: str) -> None:
        log.write(s + "\n")
        log.flush()
    logln(f"== update_prices {datetime.now().isoformat(timespec='seconds')} ==")
    try:
        # 1. catálogo oficial de Nous Portal (inference-api), sin OpenRouter
        out = run([sys.executable, "fetch_prices.py"], timeout=300)
        logln(" " + out.strip())
        doc = json.loads((BASE / "prices.json").read_text(encoding="utf-8"))
        # 3. histórico SQL + export web
        insert_history(doc)
        # 4. despliega (index.html, prices.json, history.json, ...)
        run([sys.executable, "deploy.py"], timeout=600)
        # 5. mensaje solo si hay cambios en anclados (stdout = entrega del cron)
        msg = pinned_changes_message(doc)
        log.close()
        if msg:
            print(msg)
        return 0
    except Exception as e:
        logln(f"ERROR update_prices: {e}")
        log.close()
        print(f"ERROR actualizando precios Nous Portal: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
