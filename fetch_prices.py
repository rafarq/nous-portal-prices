#!/usr/bin/env python3
"""Genera prices.json con los precios de Nous Portal.

Fuente de precios: la inference-api oficial de Nous Portal
(https://inference-api.nousresearch.com/v1/models) — el catálogo de modelos
de Nous, con precios por token (prompt/completion). Se multiplica por 1e6
para obtener el precio por 1M tokens que muestra la web.

NO se consulta OpenRouter en ningún punto: ni la API de OpenRouter ni enlaces
a openrouter.ai. Todo sale del propio portal de Nous.

Compara contra prices_prev.json y marca: "new": true si el modelo no estaba, y
change.in / change.out = {old, pct} cuando el precio cambió (pct > 0 = subió).

Uso:
    python3 fetch_prices.py   # regenera prices.json + prices_prev.json
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
API_URL = "https://inference-api.nousresearch.com/v1/models"
PREV_FILE = BASE / "prices_prev.json"
OUT_FILE = BASE / "prices.json"
PCT_EPS = 0.05  # mínimo % de variación para considerarlo cambio


def fetch_catalog() -> list[dict]:
    """Modelos y precios del catálogo oficial de Nous (inference-api)."""
    req = urllib.request.Request(
        API_URL,
        headers={"User-Agent": "nous-portal-prices/2.0 (Rafa; solo Nous Portal)"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.load(r)
    return list(data.get("data") or [])


def parse_catalog(raw: list[dict]) -> list[dict]:
    """Convierte el catálogo de la inference-api en la lista de modelos.

    - id visible = canonical_slug (con fecha) si existe, si no el id. Es el
      mismo id que usaba la web (el que el portal enlazaba).
    - Precio por 1M = pricing.prompt/completion (por token) * 1e6.
    - Los modelos batch vienen como id con sufijo ':batch' pero comparten
      canonical_slug con el normal; se descarta el batch si existe el normal.
    """
    raw = [m for m in raw if m.get("id") and m.get("pricing")]
    by_cs: dict[str, dict] = {}
    for m in raw:
        cs = m.get("canonical_slug") or m["id"]
        is_batch = m["id"].endswith(":batch")
        price = m.get("pricing") or {}
        prompt = price.get("prompt")
        completion = price.get("completion")
        if prompt is None or completion is None:
            continue
        entry = {
            "id": cs,
            "name": m.get("name") or cs,
            "in": round(float(prompt) * 1e6, 4),
            "out": round(float(completion) * 1e6, 4),
            "ctx": m.get("context_length") or 0,
            "_batch": is_batch,
        }
        prev = by_cs.get(cs)
        # Prioridad: entrada normal (no batch) sobre la batch.
        if prev is None or (not is_batch and prev["_batch"]):
            by_cs[cs] = entry
    models = []
    for e in by_cs.values():
        e.pop("_batch", None)
        models.append(e)
    return models


def diff(prev: dict[str, dict], models: list[dict], first_run: bool) -> list[dict]:
    out = []
    for m in models:
        p = prev.get(m["id"])
        entry = {**m, "new": (not first_run) and p is None, "change": {"in": None, "out": None}}
        if p:
            for key in ("in", "out"):
                old = p.get(key)
                new = m[key]
                if old is not None and abs(old - new) > 1e-9:
                    pct = round((new - old) / old * 100, 1) if old else None
                    entry["change"][key] = {"old": old, "pct": pct}
        out.append(entry)
    return out


def main() -> int:
    try:
        raw = fetch_catalog()
    except Exception as e:
        print(f"ERROR: no se pudo obtener el catálogo de Nous Portal ({e})")
        return 1
    models = parse_catalog(raw)
    if not models:
        print("ERROR: no se obtuvo ningún modelo del catálogo de Nous Portal")
        return 1

    first_run = not PREV_FILE.exists()
    prev_raw: dict = {}
    if PREV_FILE.exists():
        prev_raw = json.loads(PREV_FILE.read_text()).get("models", {})
    prev = {m["id"]: m for m in prev_raw}

    entries = diff(prev, models, first_run)
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "inference-api.nousresearch.com (Nous Portal)",
        "total": len(entries),
        "models": entries,
    }
    OUT_FILE.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    PREV_FILE.write_text(
        json.dumps({"models": [{k: m[k] for k in ("id", "in", "out")} for m in entries]}, ensure_ascii=False),
        encoding="utf-8",
    )

    nuevos = sum(1 for m in entries if m["new"])
    subidos = sum(1 for m in entries if (m["change"]["in"] or {}).get("pct", 0) > 0 or (m["change"]["out"] or {}).get("pct", 0) > 0)
    bajados = sum(1 for m in entries if (m["change"]["in"] or {}).get("pct", 0) < 0 or (m["change"]["out"] or {}).get("pct", 0) < 0)
    print(f"OK: {len(entries)} modelos | nuevos: {nuevos} | subidos: {subidos} | bajados: {bajados}")
    print(f"  -> {OUT_FILE.name} / {PREV_FILE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
