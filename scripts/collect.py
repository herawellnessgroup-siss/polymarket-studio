"""Collecteur Polymarket — tourne toutes les heures via GitHub Actions.

1. Lit les 100 marchés ouverts les plus échangés (API publique Gamma).
2. Calcule la note A–E et le niveau de risque (même logique que le dashboard).
3. Archive un instantané dans data/history/AAAA-MM-JJ.jsonl.
4. Portefeuille fictif : ouvre une mise virtuelle sur le favori de chaque marché
   qui passe en A ou B (100 $ risque faible, 50 $ modéré, 25 $ élevé),
   puis solde la position quand Polymarket a tranché.
Aucun argent réel, aucun ordre passé : lecture seule.
"""
import json, math, os, re, sys, urllib.request, urllib.parse
from datetime import datetime, timezone, date

API = "https://gamma-api.polymarket.com/markets"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
MISE_BASE = 100
FACTEUR = {"Faible": 1, "Modéré": 0.5, "Élevé": 0.25}

THEMES = [
    ("Élections US", r"midterm|senate|house|governor|balance of power|presidential|nomination|NC-\d"),
    ("Fed & taux", r"\bfed\b|interest rate|rate (cut|hike)"),
    ("Moyen-Orient", r"iran|israel|hormuz|knesset|ra'am|netanyahu|gaza|lebanon"),
    ("France 2027", r"french presidential|france|lagarde|bardella|le pen|lisnard|villepin|cazeneuve|macron"),
    ("Crypto", r"bitcoin|ethereum|solana|token|fdv|predict\.fun|1win|crypto"),
    ("Sport & esport", r"open:| vs\.? |worlds|champions league|\bf1\b|spread:|handicap|lol:|t20|nba|nfl|premier league|super bowl"),
    ("Géopolitique", r"china|taiwan|putin|russia|ukraine|nato|xi jinping|spain|taipei|venezuela"),
    ("Tech & IA", r"anthropic|openai|ai model|google|apple|nvidia|tesla"),
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "polymarket-studio/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def fetch_top():
    if os.environ.get("PM_FIXTURE"):  # test local
        return json.load(open(os.environ["PM_FIXTURE"]))
    q = urllib.parse.urlencode({"limit": 100, "closed": "false", "order": "volume24hr",
                                "ascending": "false", "liquidity_num_min": 10000})
    return get(f"{API}?{q}")


def fetch_by_ids(ids):
    out = []
    ids = list(ids)
    for i in range(0, len(ids), 50):
        q = urllib.parse.urlencode([("id", x) for x in ids[i:i + 50]] + [("limit", 50)])
        out += get(f"{API}?{q}")
    return out


def lg(x, lo, hi):
    if not x or x <= 0:
        return 0.0
    return max(0.0, min(1.0, (math.log10(x) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def score_market(m, today):
    try:
        p = float(json.loads(m.get("outcomePrices") or "[]")[0])
    except Exception:
        return None
    end = m.get("endDateIso") or (str(m.get("endDate") or "")[:10] or None)
    if not end:
        return None
    jours = (date.fromisoformat(end) - today).days
    if jours < 0:
        return None
    ev = (m.get("events") or [{}])[0]
    text = (m.get("question") or "") + " " + (ev.get("title") or "")
    theme = next((n for n, rx in THEMES if re.search(rx, text, re.I)), "Divers")
    liq, v24, v1w = num(m.get("liquidityNum")) or 0, num(m.get("volume24hr")) or 0, num(m.get("volume1wk")) or 0
    acc = v24 / (v1w / 7) if v1w else 0
    d1, w1, spread = num(m.get("oneDayPriceChange")) or 0, num(m.get("oneWeekPriceChange")) or 0, num(m.get("spread")) or 0
    fav = max(p, 1 - p)
    joue = fav >= 0.98
    zone = 1.0 if 0.15 <= p <= 0.85 else max(0.0, 1 - min(abs(p - 0.15), abs(p - 0.85)) / 0.13)
    score = 30 * lg(liq, 1e4, 5e6) + 20 * lg(v24, 1e4, 2e6) + 20 * min(acc / 3, 1) + 15 * min(abs(d1) / 0.1, 1) + 15 * zone
    if joue:
        score = min(score, 20)
    score = round(score)
    note = "A" if score >= 75 else "B" if score >= 60 else "C" if score >= 45 else "D" if score >= 30 else "E"
    pts = 0
    if jours > 180: pts += 2
    elif jours > 60: pts += 1
    if jours <= 2: pts += 1
    if min(p, 1 - p) < 0.1 and not joue: pts += 1
    if abs(w1) >= 0.15 or abs(d1) >= 0.1: pts += 2
    if spread > 0.02: pts += 1
    if liq < 50000: pts += 1
    if re.search(r"consensus of credible reporting|sole discretion|ambigu", m.get("description") or "", re.I): pts += 1
    if theme == "Sport & esport": pts += 1
    risque = "Élevé" if pts >= 4 else "Modéré" if pts >= 2 else "Faible"
    return dict(id=str(m["id"]), question=m.get("question"), theme=theme, slug=ev.get("slug") or m.get("slug"),
                prix_oui=p, favori="OUI" if p >= 0.5 else "NON", cote_favori=fav, jours=jours, fin=end,
                liquidite=round(liq), volume_24h=round(v24), acceleration=round(acc, 2),
                var_24h=d1, var_7j=w1, score=score, note=note, risque=risque, joue=joue)


def load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def main():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    today = now.date()
    rows = [r for r in (score_market(m, today) for m in fetch_top()) if r]
    rows.sort(key=lambda r: -r["score"])

    # 1. dernier état + historique
    save(os.path.join(DATA, "latest.json"), {"at": ts, "markets": rows})
    hist = os.path.join(DATA, "history", f"{today.isoformat()}.jsonl")
    os.makedirs(os.path.dirname(hist), exist_ok=True)
    with open(hist, "a") as f:
        for r in rows:
            f.write(json.dumps({"at": ts, "id": r["id"], "prix_oui": r["prix_oui"], "volume_24h": r["volume_24h"],
                                "score": r["score"], "note": r["note"], "risque": r["risque"]}) + "\n")

    # 2. portefeuille fictif : ouvertures
    ppath = os.path.join(DATA, "paper", "positions.json")
    pos = load(ppath, [])
    held = {p["id"] for p in pos}
    # un seul pari par événement (élection, match…) : ses marchés sont liés,
    # miser sur plusieurs reviendrait à doubler la même mise
    events = {p["slug"] for p in pos if p["statut"] == "ouvert"}
    for r in rows:
        if r["note"] in ("A", "B") and not r["joue"] and r["jours"] >= 1 and r["id"] not in held and r["slug"] not in events:
            mise = MISE_BASE * FACTEUR[r["risque"]]
            pos.append(dict(id=r["id"], question=r["question"], theme=r["theme"], slug=r["slug"],
                            pari=r["favori"], prix_entree=round(r["cote_favori"], 4),
                            mise=mise, gain_potentiel=round(mise * (1 / r["cote_favori"] - 1), 2),
                            note=r["note"], risque=r["risque"], ouvert_le=ts, fin=r["fin"],
                            statut="ouvert", resultat=None, pnl=None, solde_le=None))
            held.add(r["id"])
            events.add(r["slug"])

    # 3. portefeuille fictif : soldes des marchés tranchés
    ouverts = [p for p in pos if p["statut"] == "ouvert"]
    if ouverts and not os.environ.get("PM_FIXTURE"):
        etat = {str(m["id"]): m for m in fetch_by_ids(p["id"] for p in ouverts)}
        for p in ouverts:
            m = etat.get(p["id"])
            if not m or not m.get("closed"):
                continue
            try:
                yes = float(json.loads(m.get("outcomePrices") or "[]")[0])
            except Exception:
                continue
            if 0.02 < yes < 0.98:
                continue  # pas encore tranché net
            gagnant = "OUI" if yes >= 0.98 else "NON"
            win = gagnant == p["pari"]
            p.update(statut="soldé", resultat="gagné" if win else "perdu",
                     pnl=p["gain_potentiel"] if win else -p["mise"], solde_le=ts)
    save(ppath, pos)

    # 4. synthèse
    soldes = [p for p in pos if p["statut"] == "soldé"]
    mise_soldee = sum(p["mise"] for p in soldes)
    pnl = sum(p["pnl"] for p in soldes)
    save(os.path.join(DATA, "paper", "summary.json"), {
        "at": ts, "positions": len(pos), "ouvertes": len(pos) - len(soldes), "soldees": len(soldes),
        "gagnees": sum(1 for p in soldes if p["resultat"] == "gagné"),
        "mise_engagee": sum(p["mise"] for p in pos if p["statut"] == "ouvert"),
        "mise_soldee": mise_soldee, "pnl": round(pnl, 2),
        "roi": round(pnl / mise_soldee, 4) if mise_soldee else None,
    })
    print(f"{ts} — {len(rows)} marchés notés, {len(pos)} positions fictives ({len(soldes)} soldées, P&L {pnl:+.2f} $)")


if __name__ == "__main__":
    sys.exit(main())
