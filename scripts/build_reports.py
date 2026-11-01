#!/usr/bin/env python3
"""Genera data/reports.json (informes semanales) a partir de data/trades.json y data/account.json.
No usa credenciales: solo los datos ya sincronizados. Una semana = lunes a viernes por fecha de cierre;
se publica cuando el viernes ya paso. El rendimiento se calcula sobre el saldo al inicio de la semana."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

def parse(s):
    return datetime.strptime(s, "%m/%d/%Y %H:%M")

def main():
    trades = json.loads((DATA / "trades.json").read_text(encoding="utf-8")).get("trades", [])
    acc = json.loads((DATA / "account.json").read_text(encoding="utf-8"))
    currency = (acc.get("stats") or {}).get("currency") or ""
    rows = []
    for t in trades:
        if not t.get("closeTime"):
            continue
        rows.append((parse(t["closeTime"]), t))
    rows.sort(key=lambda r: r[0])
    today = datetime.now(timezone.utc).date()
    weeks = {}
    balance = 0.0
    for when, t in rows:
        monday = (when - timedelta(days=when.weekday())).date()
        w = weeks.setdefault(monday, {"start_balance": None, "pnl": [], "flows": 0.0})
        if w["start_balance"] is None:
            w["start_balance"] = balance
        amount = float(t.get("profit") or 0) + float(t.get("swap") or 0)
        if t.get("action") in ("Buy", "Sell"):
            w["pnl"].append(amount)
        else:                       # depositos / retiros
            w["flows"] += amount
            if not w["pnl"]:        # deposito antes de operar en la semana: cuenta como saldo inicial
                w["start_balance"] += amount
        balance += amount
    reports = []
    for monday, w in sorted(weeks.items()):
        friday = monday + timedelta(days=4)
        if friday >= today or not w["pnl"]:
            continue
        net = sum(w["pnl"])
        gp = sum(p for p in w["pnl"] if p > 0)
        gl = -sum(p for p in w["pnl"] if p < 0)
        base = w["start_balance"] or 0.0
        reports.append({
            "status": "published",
            "weekStart": monday.isoformat(),
            "weekEnd": friday.isoformat(),
            "periodLabel": f"{monday.strftime('%d/%m/%Y')} – {friday.strftime('%d/%m/%Y')}",
            "netProfit": round(net, 2),
            "currency": currency,
            "returnPct": round(100 * net / base, 2) if base > 0 else 0.0,
            "profitFactor": round(gp / gl, 2) if gl > 0 else None,
            "tradeCount": len(w["pnl"]),
            "startBalance": round(base, 2),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        })
    # conservar las fechas si el contenido no cambio (evita un commit cada 4 horas sin novedades)
    prev_path = DATA / "reports.json"
    prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path.exists() else {}
    prev_by_week = {r.get("weekStart"): r for r in prev.get("reports", [])}
    strip = lambda r: {k: v for k, v in r.items() if k != "updatedAt"}
    changed = False
    for r in reports:
        old = prev_by_week.get(r["weekStart"])
        if old and strip(old) == strip(r):
            r["updatedAt"] = old.get("updatedAt", r["updatedAt"])
        else:
            changed = True
    if len(reports) != len(prev.get("reports", [])):
        changed = True
    out = {"schemaVersion": 1, "account": acc.get("account"),
           "updatedAt": datetime.now(timezone.utc).isoformat() if changed else prev.get("updatedAt"),
           "reports": reports}
    (DATA / "reports.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Informes semanales: {len(reports)}")

if __name__ == "__main__":
    main()
