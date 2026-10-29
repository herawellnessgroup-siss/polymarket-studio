"""Broker fictif — test d'un mois avec un capital virtuel.

Règles (écrites ici, appliquées à chaque passage horaire) :
- Capital de départ : CAPITAL_INITIAL $ fictifs. Test du DEBUT à FIN.
- ENTRÉE : marché noté A ou B, pas joué d'avance, qui se tranche avant la fin du test,
  un seul pari par événement. Mise sur le favori : 3 % du capital (risque faible),
  1,5 % (modéré), 0,5 % (élevé). Plafonds : 60 % du capital engagé au total,
  25 % par thème. Pas de nouvelle entrée après la fin du test.
- SORTIE ANTICIPÉE : prise de bénéfice dès que la position a capté 60 % de son gain
  potentiel ; stop-loss si elle a perdu 50 % de la mise.
- RÉSOLUTION : quand Polymarket tranche, la position paie 1 $ par part si le pari est juste, 0 sinon.
Prix = dernier prix affiché ; frais et glissement non comptés.
"""
import json, os, urllib.parse, urllib.request
from datetime import date

CAPITAL_INITIAL = 1_000
DEBUT = "2026-10-30"
FIN = "2026-11-30"
TAILLE = {"Faible": 0.03, "Modéré": 0.015, "Élevé": 0.005}
PLAFOND_TOTAL, PLAFOND_THEME = 0.60, 0.25
PRISE_BENEF, STOP = 0.60, 0.50

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "data", "paper")
API = "https://gamma-api.polymarket.com/markets"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "polymarket-studio/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def fetch_by_ids(ids):
    if os.environ.get("PM_FIXTURE_IDS"):
        return json.load(open(os.environ["PM_FIXTURE_IDS"]))
    ids, out = list(ids), []
    for i in range(0, len(ids), 50):
        out += _get(API + "?" + urllib.parse.urlencode([("id", x) for x in ids[i:i + 50]] + [("limit", 50)]))
    return out


def _load(name, default):
    path = os.path.join(P, name)
    return json.load(open(path)) if os.path.exists(path) else default


def _save(name, obj):
    os.makedirs(P, exist_ok=True)
    with open(os.path.join(P, name), "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def usd(x):
    return f"{x:,.0f} $".replace(",", " ")


def run_broker(rows, ts, today):
    state = _load("state.json", {"capital_initial": CAPITAL_INITIAL, "cash": CAPITAL_INITIAL, "debut": DEBUT, "fin": FIN})
    pos = _load("positions.json", [])
    journal = _load("journal.json", [])
    equity = _load("equity.json", [])
    by_id = {r["id"]: r for r in rows}

    def log(action, p, detail, montant=None, pnl=None):
        journal.append(dict(at=ts, action=action, id=p["id"], marche=p["question"], pari=p["pari"],
                            prix=p.get("prix_actuel", p["prix_entree"]), montant=montant, pnl=pnl, detail=detail))

    # 1. suivi des positions ouvertes
    ouvertes = [p for p in pos if p["statut"] == "ouvert"]
    if ouvertes:
        live = {str(m["id"]): m for m in fetch_by_ids(p["id"] for p in ouvertes)}
        for p in ouvertes:
            m = live.get(p["id"])
            if not m:
                continue
            try:
                yes = float(json.loads(m.get("outcomePrices") or "[]")[0])
            except Exception:
                continue
            cur = yes if p["pari"] == "OUI" else 1 - yes
            p["prix_actuel"] = round(cur, 4)
            p["valeur"] = round(p["parts"] * cur, 2)
            p["pnl_latent"] = round(p["valeur"] - p["mise"], 2)
            if m.get("closed") and (yes >= 0.98 or yes <= 0.02):
                win = cur >= 0.98
                retour = p["parts"] if win else 0.0
                state["cash"] += retour
                p.update(statut="soldé", sortie="résolution", resultat="gagné" if win else "perdu",
                         pnl=round(retour - p["mise"], 2), ferme_le=ts, valeur=round(retour, 2), pnl_latent=0)
                log("RÉSOLUTION", p, f"Polymarket a tranché : pari {'juste' if win else 'perdu'}.", round(retour, 2), p["pnl"])
                continue
            gain_pot = p["parts"] - p["mise"]
            if p["pnl_latent"] >= PRISE_BENEF * gain_pot and gain_pot > 0:
                raison = f"Prise de bénéfice : {p['pnl_latent']:+.0f} $ déjà captés sur {gain_pot:.0f} $ possibles (seuil {int(PRISE_BENEF*100)} %)."
            elif p["pnl_latent"] <= -STOP * p["mise"]:
                raison = f"Stop-loss : la position a perdu {-p['pnl_latent']:.0f} $ sur {p['mise']:.0f} $ misés (seuil {int(STOP*100)} %)."
            else:
                continue
            state["cash"] += p["valeur"]
            p.update(statut="soldé", sortie="anticipée", resultat="gagné" if p["pnl_latent"] > 0 else "perdu",
                     pnl=p["pnl_latent"], ferme_le=ts, pnl_latent=0)
            log("SORTIE", p, raison, p["valeur"], p["pnl"])

    # 2. valeur du portefeuille
    ouvertes = [p for p in pos if p["statut"] == "ouvert"]
    engage = sum(p.get("valeur", p["mise"]) for p in ouvertes)
    valeur = state["cash"] + engage

    # 3. nouvelles entrées
    if today <= date.fromisoformat(FIN):
        events = {p["slug"] for p in ouvertes}
        held = {p["id"] for p in pos}
        par_theme = {}
        for p in ouvertes:
            par_theme[p["theme"]] = par_theme.get(p["theme"], 0) + p["mise"]
        for r in rows:  # déjà triés du meilleur score au moins bon
            if r["note"] not in ("A", "B") or r["joue"] or r["jours"] < 1 or r["id"] in held or r["slug"] in events:
                continue
            if date.fromisoformat(r["fin"]) > date.fromisoformat(FIN):
                continue
            mise = round(valeur * TAILLE[r["risque"]], 2)
            if engage + mise > PLAFOND_TOTAL * valeur or par_theme.get(r["theme"], 0) + mise > PLAFOND_THEME * valeur or mise > state["cash"]:
                continue
            prix = r["cote_favori"]
            c = r["composantes"]
            pourquoi = (f"Note {r['note']} ({r['score']}/100) : liquidité {c['liquidite']}/30, volume {c['volume']}/20, "
                        f"accélération {c['acceleration']}/20 (×{r['acceleration']}), mouvement {c['mouvement']}/15, zone de cote {c['zone']}/15. "
                        f"Favori {r['favori']} à {prix*100:.1f} %. Risque {r['risque'].lower()}"
                        + (f" ({', '.join(r['raisons_risque'])})" if r["raisons_risque"] else "")
                        + f". Mise {TAILLE[r['risque']]*100:g} % du capital. Tranché d'ici le {r['fin']}.")
            p = dict(id=r["id"], question=r["question"], theme=r["theme"], slug=r["slug"], pari=r["favori"],
                     prix_entree=round(prix, 4), prix_actuel=round(prix, 4), mise=mise, parts=round(mise / prix, 4),
                     gain_potentiel=round(mise / prix - mise, 2), valeur=mise, pnl_latent=0.0,
                     note=r["note"], score=r["score"], risque=r["risque"], pourquoi=pourquoi,
                     ouvert_le=ts, fin=r["fin"], statut="ouvert", sortie=None, resultat=None, pnl=None, ferme_le=None)
            pos.append(p)
            state["cash"] -= mise
            engage += mise
            held.add(r["id"]); events.add(r["slug"])
            par_theme[r["theme"]] = par_theme.get(r["theme"], 0) + mise
            log("ENTRÉE", p, pourquoi, -mise, None)

    # 4. courbe de valeur et bilan
    ouvertes = [p for p in pos if p["statut"] == "ouvert"]
    engage = sum(p.get("valeur", p["mise"]) for p in ouvertes)
    valeur = round(state["cash"] + engage, 2)
    equity.append(dict(at=ts, valeur=valeur, cash=round(state["cash"], 2), engage=round(engage, 2)))
    soldes = [p for p in pos if p["statut"] == "soldé"]
    state.update(
        cash=round(state["cash"], 2), maj=ts, valeur=valeur, pnl_total=round(valeur - CAPITAL_INITIAL, 2),
        pnl_realise=round(sum(p["pnl"] for p in soldes), 2), pnl_latent=round(sum(p["pnl_latent"] for p in ouvertes), 2),
        engage=round(engage, 2), ouvertes=len(ouvertes), soldees=len(soldes),
        gagnees=sum(1 for p in soldes if p["resultat"] == "gagné"),
        jours_restants=max(0, (date.fromisoformat(FIN) - today).days),
    )
    _save("state.json", state)
    _save("positions.json", pos)
    _save("journal.json", journal)
    _save("equity.json", equity)
