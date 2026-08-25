#!/usr/bin/env python3
"""Busca estatisticas do GoatCounter e atualiza o Gist usado pelo painel /stats.

Variaveis de ambiente necessarias:
  GOATCOUNTER_TOKEN  - token da API do GoatCounter (Settings > API, permissao de leitura)
  GOATCOUNTER_SITE   - subdominio do site, ex: toquedemar (sem .goatcounter.com)
  GIST_TOKEN         - token do GitHub com escopo "gist"
  GIST_ID            - id do gist que guarda o stats.json
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

GOATCOUNTER_TOKEN = os.environ["GOATCOUNTER_TOKEN"]
GOATCOUNTER_SITE = os.environ["GOATCOUNTER_SITE"]
GIST_TOKEN = os.environ["GIST_TOKEN"]
GIST_ID = os.environ["GIST_ID"]

BASE_URL = f"https://{GOATCOUNTER_SITE}.goatcounter.com/api/v0"


def gc_get(path, params=None):
    url = f"{BASE_URL}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {GOATCOUNTER_TOKEN}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_all_hits():
    items = []
    after = None
    while True:
        params = {"daily": "true", "limit": 100}
        if after:
            params["after"] = after
        data = gc_get("/stats/hits", params)
        hits = data.get("hits", [])
        items.extend(hits)
        if not data.get("more") or not hits:
            break
        after = hits[-1]["id"]
    return items


def build_stats_json(hits):
    items = []
    for hit in hits:
        days = {}
        for s in hit.get("stats", []) or []:
            day = s.get("day")
            count = s.get("daily", 0)
            if day:
                days[day] = days.get(day, 0) + count
        items.append({
            "path": hit.get("path", ""),
            "title": hit.get("title", "") or hit.get("path", ""),
            "event": bool(hit.get("event")),
            "days": days,
        })
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }


def update_gist(stats):
    content = json.dumps(stats, ensure_ascii=False, indent=2)
    payload = json.dumps({"files": {"stats.json": {"content": content}}}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/gists/{GIST_ID}",
        data=payload,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {GIST_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def main():
    hits = fetch_all_hits()
    stats = build_stats_json(hits)
    update_gist(stats)
    print(f"OK: {len(stats['items'])} itens atualizados em {stats['updated_at']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao atualizar stats: {exc}", file=sys.stderr)
        sys.exit(1)
