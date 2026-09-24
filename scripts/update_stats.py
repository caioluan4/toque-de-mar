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
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

GOATCOUNTER_TOKEN = os.environ["GOATCOUNTER_TOKEN"]
GOATCOUNTER_SITE = os.environ["GOATCOUNTER_SITE"]
GIST_TOKEN = os.environ["GIST_TOKEN"]
GIST_ID = os.environ["GIST_ID"]

BASE_URL = f"https://{GOATCOUNTER_SITE}.goatcounter.com/api/v0"

# Sem start/end a API devolve só os últimos dias; pedimos desde a instalação do analytics.
STATS_START = "2026-08-24T00:00:00Z"

RETRIES = 3
RETRY_DELAY_SECONDS = 5


def with_retries(func, *args, **kwargs):
    last_exc = None
    for attempt in range(1, RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last_exc = exc
            if attempt < RETRIES:
                print(f"Tentativa {attempt} falhou ({exc}); tentando de novo em {RETRY_DELAY_SECONDS}s...", file=sys.stderr)
                time.sleep(RETRY_DELAY_SECONDS)
    raise last_exc


def gc_get(path, params=None):
    url = f"{BASE_URL}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {GOATCOUNTER_TOKEN}",
        "Accept": "application/json",
    })

    def _do():
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    return with_retries(_do)


def fetch_all_hits():
    items = []
    after = None
    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    while True:
        params = {"daily": "true", "limit": 100, "start": STATS_START, "end": end}
        if after:
            params["after"] = after
        data = gc_get("/stats/hits", params)
        hits = data.get("hits", [])
        items.extend(hits)
        if not data.get("more") or not hits:
            break
        after = hits[-1].get("path_id") or hits[-1].get("id")
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


def fetch_current_gist_stats():
    req = urllib.request.Request(
        f"https://api.github.com/gists/{GIST_ID}",
        headers={
            "Authorization": f"Bearer {GIST_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
    )

    def _do():
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    gist = with_retries(_do)
    file = gist.get("files", {}).get("stats.json")
    if not file:
        return None
    content = file.get("content")
    if file.get("truncated") and file.get("raw_url"):
        with urllib.request.urlopen(file["raw_url"], timeout=30) as resp:
            content = resp.read().decode()
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return None


def merge_with_previous(new_stats, old_stats):
    """Mantém dias que já estavam no Gist, mesmo se a API deixar de devolvê-los."""
    if not old_stats:
        return new_stats
    merged = {}
    for item in old_stats.get("items", []) + new_stats["items"]:
        key = (item.get("path", ""), bool(item.get("event")))
        entry = merged.setdefault(key, {
            "path": item.get("path", ""),
            "title": item.get("title", ""),
            "event": bool(item.get("event")),
            "days": {},
        })
        if item.get("title"):
            entry["title"] = item["title"]
        for day, count in (item.get("days") or {}).items():
            entry["days"][day] = max(entry["days"].get(day, 0), count)
    new_stats["items"] = list(merged.values())
    return new_stats


def update_gist(stats):
    content = json.dumps(stats, ensure_ascii=False, indent=2)
    payload = json.dumps({"files": {"stats.json": {"content": content}}}).encode()

    def _do():
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

    with_retries(_do)


def main():
    hits = fetch_all_hits()
    stats = merge_with_previous(build_stats_json(hits), fetch_current_gist_stats())
    update_gist(stats)
    print(f"OK: {len(stats['items'])} itens atualizados em {stats['updated_at']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao atualizar stats: {exc}", file=sys.stderr)
        sys.exit(1)
