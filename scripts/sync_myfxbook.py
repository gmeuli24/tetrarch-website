#!/usr/bin/env python3
"""Daily Myfxbook sync for Tetrarch. Secrets are read only from environment."""
import json, os, sys, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.myfxbook.com/api"
ACCOUNT_ID = str(os.environ.get("MYFXBOOK_ACCOUNT_ID", "12278068"))
EMAIL = os.environ["MYFXBOOK_EMAIL"]
PASSWORD = os.environ["MYFXBOOK_PASSWORD"]
DATA = Path("data")
DATA.mkdir(exist_ok=True)

def api(method, **params):
    query = urllib.parse.urlencode(params)
    url = f"{BASE}/{method}.json?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "Tetrarch-Results-Sync/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise RuntimeError(f"Myfxbook {method}: {payload.get('message') or 'API error'}")
    return payload

def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def normalize_trade(t):
    # Keep only public reporting fields; do not store API session or credentials.
    return {
        "openTime": t.get("openTime") or t.get("openDate"),
        "closeTime": t.get("closeTime") or t.get("closeDate"),
        "symbol": t.get("symbol"),
        "action": t.get("action"),
        "profit": float(t.get("profit") or 0),
        "commission": float(t.get("commission") or 0),
        "swap": float(t.get("interest") if t.get("interest") is not None else (t.get("swap") or 0)),
        "pips": float(t.get("pips") or 0),
    }

def trade_key(t):
    return "|".join(str(t.get(k) or "") for k in ("openTime","closeTime","symbol","action","profit","commission","swap"))

session = None
try:
    login = api("login", email=EMAIL, password=PASSWORD)
    session = login.get("session")
    if not session:
        raise RuntimeError("Myfxbook did not return a session")
    accounts_payload = api("get-my-accounts", session=session)
    accounts = accounts_payload.get("accounts") or []
    account = next((a for a in accounts if str(a.get("id")) == ACCOUNT_ID), None)
    if account is None:
        available = ", ".join(str(a.get("id")) for a in accounts)
        raise RuntimeError(f"Account id {ACCOUNT_ID} not found in get-my-accounts. Returned ids: {available or 'none'}. Do not assume the public profile id is the API account id.")
    history_payload = api("get-history", session=session, id=ACCOUNT_ID)
    history = history_payload.get("history") or []
    normalized = [normalize_trade(t) for t in history]
    trades_file = DATA / "trades.json"
    stored = read_json(trades_file, {"schemaVersion":1,"account":ACCOUNT_ID,"syncedAt":None,"trades":[]})
    by_key = {trade_key(t): t for t in stored.get("trades", [])}
    for t in normalized:
        if t.get("closeTime"):
            by_key[trade_key(t)] = t
    merged = sorted(by_key.values(), key=lambda t: (t.get("closeTime") or "", t.get("openTime") or ""))
    write_json(trades_file, {"schemaVersion":1,"account":ACCOUNT_ID,"syncedAt":datetime.now(timezone.utc).isoformat(),"trades":merged})
    # Public-safe account fields only; exclude login/session and other personal metadata.
    fields = ("name","accountId","gain","absGain","daily","monthly","profit","balance","equity",
              "drawdown","profitFactor","pips","lastUpdateDate","currency","demo","leverage","server","firstTradeDate")
    stats = {k: account.get(k) for k in fields if k in account}
    server = stats.get("server")
    if isinstance(server, dict):
        stats["server"] = server.get("name")
    write_json(DATA / "account.json", {"schemaVersion":1,"account":ACCOUNT_ID,
        "syncedAt":datetime.now(timezone.utc).isoformat(),"stats":stats})
    print(f"Sync OK: account={ACCOUNT_ID}, API history={len(normalized)}, archived closed trades={len(merged)}")
finally:
    if session:
        try:
            api("logout", session=session)
        except Exception as exc:
            print(f"Logout warning: {exc}", file=sys.stderr)
