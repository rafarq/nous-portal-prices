#!/usr/bin/env python3
"""Genera prices.json con los precios de Nous Portal.

Fuente de precios: markdown de https://portal.nousresearch.com/ (capturado con
web_extract y guardado como portal.md) — son los precios EXACTOS que muestra el
portal (in $X / out $Y per 1M). El nombre y el contexto se cruzan con la API
pública de OpenRouter (el portal enlaza a openrouter.ai por modelo).

Compara contra prices_prev.json y marca: "new": true si el modelo no estaba, y
change.in / change.out = {old, pct} cuando el precio cambió (pct > 0 = subió).

Uso:
    python3 fetch_prices.py [portal.md]   # regenera prices.json + prices_prev.json
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
PORTAL_MD = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "portal.md"
API_URL = "https://openrouter.ai/api/v1/models"
PREV_FILE = BASE / "prices_prev.json"
OUT_FILE = BASE / "prices.json"

PRICE_RE = re.compile(r"in \$([\d.]+)\s*/\s*out \$([\d.]+)\s+per\s+1M")
FLAT_RE = re.compile(r"\$([\d.]+)/1M")  # formato "in $0.00/1M" (free) o flat "$X/1M"
BATCH_RE = re.compile(r"\(batch\)", re.IGNORECASE)
LINK_RE = re.compile(r"\[([^\]]+)\]\((https://openrouter\.ai/[^)]+)\)")


def fetch_catalog() -> dict[str, dict]:
    """id/canonical_slug -> {name, ctx} desde la API de OpenRouter."""
    req = urllib.request.Request(API_URL, headers={"User-Agent": "nous-portal-prices/1.0"})
    out: dict[str, dict] = {}
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        for m in data.get("data", []):
            entry = {"name": m.get("name") or m["id"], "ctx": m.get("context_length") or 0}
            out[m["id"]] = entry
            cs = m.get("canonical_slug")
            if cs and cs != m["id"]:
                out.setdefault(cs, entry)
    except Exception as e:
        print(f"AVISO: no se pudo obtener catálogo OpenRouter ({e}); sin nombres/contexto")
    return out


def parse_portal(text: str) -> list[dict]:
    """Parsea el markdown del portal de Nous.

    Reglas para que los precios reflejen SIEMPRE lo que muestra el portal
    (fuente correcta = portal.nousresearch.com, NO la API de OpenRouter,
    que añade margen):

    - El portal lista algunos modelos DOS veces con el mismo slug: la entrada
      normal y la variante (batch) a mitad de precio. Se prioriza SIEMPRE la
      normal: si para un slug existe al menos una entrada sin "(batch)", se
      descartan las batch.
    - Formato flat "$X/1M" (p. ej. LongCat 2.0:free): in = out = X (0 para free).
    - El nombre/ctx se cruza con la API de OpenRouter solo como metadato.
    """
    catalog = fetch_catalog()
    raw: dict[str, list[dict]] = {}
    for m in LINK_RE.finditer(text):
        label, url = m.group(1), m.group(2)
        slug = url.split("openrouter.ai/", 1)[-1].split("?")[0].rstrip("/")
        if not slug:
            continue
        pm = PRICE_RE.search(label)
        if pm:
            price_in, price_out = float(pm.group(1)), float(pm.group(2))
            clean_label = PRICE_RE.sub("", label).strip()
        else:
            fm = FLAT_RE.search(label)
            if not fm:
                continue  # sin precio parseable: se omite
            price_in = price_out = float(fm.group(1))
            clean_label = FLAT_RE.sub("", label).strip()
        info = catalog.get(slug) or {}
        raw.setdefault(slug, []).append({
            "id": slug,
            "name": info.get("name") or clean_label,
            "in": round(price_in, 4),
            "out": round(price_out, 4),
            "ctx": info.get("ctx") or 0,
            "is_batch": bool(BATCH_RE.search(label)),
        })

    models = []
    for slug, entries in raw.items():
        # Prioridad: precio normal > batch (descartar batch si hay normal).
        best = next((e for e in entries if not e["is_batch"]), entries[0])
        best.pop("is_batch", None)
        models.append(best)
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
    if not PORTAL_MD.exists():
        print(f"ERROR: no existe {PORTAL_MD} — captúralo con web_extract del portal primero")
        return 1
    models = parse_portal(PORTAL_MD.read_text(encoding="utf-8"))
    if not models:
        print("ERROR: no se parseó ningún modelo del portal")
        return 1

    first_run = not PREV_FILE.exists()
    prev_raw: dict = {}
    if PREV_FILE.exists():
        prev_raw = json.loads(PREV_FILE.read_text()).get("models", {})
    prev = {m["id"]: m for m in prev_raw}

    entries = diff(prev, models, first_run)
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "portal.nousresearch.com",
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
