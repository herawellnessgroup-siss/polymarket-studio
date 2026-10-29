"""Broker fictif — test d'un mois avec un capital virtuel.

Règles (écrites ici, appliquées à chaque passage horaire) :
- Capital de départ : CAPITAL_INITIAL $ fictifs. Test du DEBUT à FIN.
- ENTRÉE : uniquement sur avis de recherche (data/research/avis.json) de moins de 48 h :
  Claude a croisé les sources (presse, sondages, données officielles, stats) et estimé
  sa propre probabilité. On entre seulement si cette probabilité dépasse la cote du marché
  d'au moins AVANTAGE_MIN (5 points), sur un marché qui se tranche avant la fin du test,
  un seul pari par événement. Mise : 3 % du capital (risque faible), 1,5 % (modéré),
  0,5 % (élevé), multipliée par la confiance de l'avis (×0,5 / ×1 / ×1,5).
  Plafonds : 60 % du capital engagé au total, 25 % par thème.
- AVIS RÉVISÉ : si un nouvel avis dit « sortir » sur une position ouverte, on solde au prix du marché.
- SORTIE ANTICIPÉE : prise de bénéfice dès que la position a capté 60 % de son gain
  potentiel ; stop-loss si elle a perdu 50 % de la mise.
- RÉSOLUTION : quand Polymarket tranche, la position paie 1 $ par part si le pari est juste, 0 sinon.
Prix = dernier prix affiché ; frais et glissement non comptés.
"""
import json, os, urllib.parse, urllib.request
from datetime import date, datetime, timezone

CAPITAL_INITIAL = 1_000
DEBUT = "2026-10-30"
FIN = "2026-11-30"
TAILLE = {"Faible": 0.03, "Modéré": 0.015, "Élevé": 0.005}
PLAFOND_TOTAL, PLAFOND_THEME = 0.60, 0.25
PRISE_BENEF, STOP = 0.60, 0.50
AVANTAGE_MIN = 0.05
AVIS_MAX_HEURES = 48
CONFIANCE = {1: 0.5, 2: 1.0, 3: 1.5}

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


def _load_research():
    path = os.path.join(ROOT, "data", "research", "avis.json")
    return json.load(open(path)) if os.path.exists(path) else []


def usd(x):
    return f"{x:,.0f} $".replace(",", " ")


def run_broker(rows, ts, today):
    state = _load("state.json", {"capital_initial": CAPITAL_INITIAL, "cash": CAPITAL_INITIAL, "debut": DEBUT, "fin": FIN})
    pos = _load("positions.json", [])
    journal = _load("journal.json", [])
    equity = _load("equity.json", [])
    by_id = {r["id"]: r for r in rows}
    avis = {str(a["id"]): a for a in _load_research()}
    now = datetime.now(timezone.utc)

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
            av = avis.get(p["id"])
            if av and av.get("verdict") == "sortir" and av.get("at", "") > p["ouvert_le"]:
                raison = "Avis révisé après recherche : " + av.get("resume", "")
            elif p["pnl_latent"] >= PRISE_BENEF * gain_pot and gain_pot > 0:
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
        for r in rows:
            av = avis.get(r["id"])
            if not av or av.get("verdict") not in ("OUI", "NON"):
                continue
            try:
                age = (now - datetime.fromisoformat(av["at"].replace("Z", "+00:00"))).total_seconds() / 3600
            except Exception:
                continue
            if age > AVIS_MAX_HEURES or r["joue"] or r["jours"] < 1 or r["id"] in held or r["slug"] in events:
                continue
            if date.fromisoformat(r["fin"]) > date.fromisoformat(FIN):
                continue
            cote_oui = r["prix_oui"]
            prix = cote_oui if av["verdict"] == "OUI" else 1 - cote_oui
            proba = float(av["proba_oui"]) if av["verdict"] == "OUI" else 1 - float(av["proba_oui"])
            avantage = proba - prix
            if avantage < AVANTAGE_MIN or prix <= 0.02 or prix >= 0.98:
                continue
            conf = int(av.get("confiance", 2))
            mise = round(valeur * TAILLE[r["risque"]] * CONFIANCE.get(conf, 1.0), 2)
            if engage + mise > PLAFOND_TOTAL * valeur or par_theme.get(r["theme"], 0) + mise > PLAFOND_THEME * valeur or mise > state["cash"]:
                continue
            sources = av.get("sources", [])
            pourquoi = (f"Recherche : {av.get('resume', '')} Ma probabilité {proba*100:.0f} % contre {prix*100:.1f} % pour le marché, "
                        f"soit un avantage de {avantage*100:.1f} points. Confiance {conf}/3. Risque {r['risque'].lower()}"
                        + (f" ({', '.join(r['raisons_risque'])})" if r["raisons_risque"] else "")
                        + f". Mise {TAILLE[r['risque']]*CONFIANCE.get(conf, 1.0)*100:g} % du capital. Note marché {r['note']} ({r['score']}/100). "
                        + f"Sources : {len(sources)}.")
            p = dict(id=r["id"], question=r["question"], theme=r["theme"], slug=r["slug"], pari=av["verdict"],
                     prix_entree=round(prix, 4), prix_actuel=round(prix, 4), mise=mise, parts=round(mise / prix, 4),
                     gain_potentiel=round(mise / prix - mise, 2), valeur=mise, pnl_latent=0.0,
                     note=r["note"], score=r["score"], risque=r["risque"], pourquoi=pourquoi,
                     proba_estimee=round(proba, 3), avantage=round(avantage, 3), confiance=conf, sources=sources,
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
