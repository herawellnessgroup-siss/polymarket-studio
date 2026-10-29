"""Registre du studio de paris sportifs fictifs (Betclic, 1 000 € virtuels, 30/10/2026 → 31/01/2027).

Toute la comptabilité passe par ce script : il applique les règles (paris/REGLES.md),
calcule les mises lui-même et refuse ce qui ne les respecte pas. Aucun argent réel.

Commandes :
  python paris/scripts/ledger.py place  FICHIER.json   # propose des paris (liste), le script valide et mise
  python paris/scripts/ledger.py settle ID RESULTAT "détail" [cote_cloture]
                                                       # RESULTAT : gagne | perdu | rembourse
  python paris/scripts/ledger.py snapshot              # recalcule le bilan et ajoute un point à la courbe
"""
import json, os, sys
from datetime import datetime, timezone, date

CAPITAL_INITIAL = 1000.0
DEBUT, FIN = "2026-10-30", "2027-01-31"
AVANTAGE_MIN = 0.05          # proba × cote ≥ 1,05
COTE_MIN, COTE_MAX = 1.30, 5.00
KELLY_FRACTION = 0.25
MISE_MAX_SIMPLE = 0.03       # 3 % de la bankroll
MISE_MAX_COMBINE = 0.01      # 1 % de la bankroll
COMBINE_JAMBES = (2, 3)
COMBINE_PROBA_JAMBE_MIN = 0.60
COMBINE_PLAFOND_SEMAINE = 0.10
EXPOSITION_MAX = 0.25        # 25 % de la bankroll en jeu au maximum
MISE_MIN = 2.0
CONFIANCE = {1: 0.5, 2: 1.0, 3: 1.25}
SPORTS = {"Football", "Tennis", "Basket", "Rugby"}

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(name, default):
    p = os.path.join(D, name)
    return json.load(open(p)) if os.path.exists(p) else default


def save(name, obj):
    os.makedirs(D, exist_ok=True)
    with open(os.path.join(D, name), "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def compte(bets):
    regle = [b for b in bets if b["statut"] in ("gagne", "perdu", "rembourse")]
    en_cours = [b for b in bets if b["statut"] == "en_cours"]
    pnl = round(sum(b["pnl"] for b in regle), 2)
    en_jeu = round(sum(b["mise"] for b in en_cours), 2)
    bankroll = round(CAPITAL_INITIAL + pnl, 2)          # valeur (mises en cours comptées au prix payé)
    dispo = round(bankroll - en_jeu, 2)
    mises_reglees = sum(b["mise"] for b in regle if b["statut"] != "rembourse")
    decides = [b for b in regle if b["statut"] != "rembourse"]
    return dict(regle=regle, en_cours=en_cours, pnl=pnl, en_jeu=en_jeu, bankroll=bankroll, dispo=dispo,
                mises_reglees=round(mises_reglees, 2), decides=decides)


def journal_add(j, action, b, detail, montant=None, pnl=None):
    j.append(dict(at=now(), action=action, id=b["id"], evenement=b["evenement"], selection=b["selection"],
                  cote=b["cote"], montant=montant, pnl=pnl, detail=detail))


def place(path):
    props = json.load(open(path))
    bets, j = load("bets.json", []), load("journal.json", [])
    out = []
    for p in props:
        c = compte(bets)
        typ = p.get("type", "simple")
        cote = float(p["cote"])
        proba = float(p["proba"])
        conf = int(p.get("confiance", 2))
        motif = None
        if date.fromisoformat(now()[:10]) > date.fromisoformat(FIN):
            motif = "test terminé"
        elif p.get("sport") not in SPORTS and typ == "simple":
            motif = "sport hors périmètre"
        elif typ == "simple" and not (COTE_MIN <= cote <= COTE_MAX):
            motif = f"cote {cote} hors de [{COTE_MIN} ; {COTE_MAX}]"
        elif proba * cote < 1 + AVANTAGE_MIN:
            motif = f"avantage insuffisant (proba × cote = {proba*cote:.3f})"
        elif typ == "combine":
            legs = p.get("jambes", [])
            if not (COMBINE_JAMBES[0] <= len(legs) <= COMBINE_JAMBES[1]):
                motif = "combiné : 2 ou 3 sélections"
            elif any(float(l["proba"]) < COMBINE_PROBA_JAMBE_MIN or float(l["proba"]) * float(l["cote"]) < 1 + AVANTAGE_MIN for l in legs):
                motif = "combiné : chaque sélection doit avoir proba ≥ 60 % et de la valeur"
        if not motif and any(b["evenement"] == p["evenement"] and b["statut"] == "en_cours" and b["type"] == "simple" for b in bets) and typ == "simple":
            motif = "déjà un pari simple en cours sur cet événement"
        kelly = (proba * cote - 1) / (cote - 1)
        cap = MISE_MAX_COMBINE if typ == "combine" else MISE_MAX_SIMPLE
        mise = round(min(cap, KELLY_FRACTION * kelly) * CONFIANCE.get(conf, 1.0) * c["bankroll"], 2)
        mise = min(mise, round(cap * c["bankroll"], 2))
        if not motif and mise < MISE_MIN:
            motif = f"mise calculée trop faible ({mise} €)"
        if not motif and c["en_jeu"] + mise > EXPOSITION_MAX * c["bankroll"]:
            motif = "plafond d'exposition atteint (25 %)"
        if not motif and typ == "combine":
            debut_sem = now()[:10]
            sem = sum(b["mise"] for b in bets if b["type"] == "combine" and (datetime.fromisoformat(debut_sem) - datetime.fromisoformat(b["place_le"][:10])).days < 7)
            if sem + mise > COMBINE_PLAFOND_SEMAINE * c["bankroll"]:
                motif = "plafond hebdo des combinés atteint (10 %)"
        if not motif and mise > c["dispo"]:
            motif = "pas assez de bankroll disponible"
        if motif:
            out.append(f"REFUSÉ  {p['evenement']} · {p['selection']} : {motif}")
            continue
        b = dict(id=f"P{len(bets)+1:04d}", place_le=now(), type=typ, sport=p.get("sport", "Multi"),
                 competition=p.get("competition", ""), evenement=p["evenement"], date_evenement=p.get("date_evenement"),
                 marche=p.get("marche", ""), selection=p["selection"], cote=round(cote, 2), proba=round(proba, 3),
                 avantage=round(proba * cote - 1, 3), confiance=conf, mise=mise,
                 gain_potentiel=round(mise * cote - mise, 2), retour_potentiel=round(mise * cote, 2),
                 jambes=p.get("jambes", []), source_cote=p.get("source_cote", "Betclic"),
                 pourquoi=p.get("pourquoi", ""), sources=p.get("sources", []),
                 statut="en_cours", resultat=None, cote_cloture=None, regle_le=None, pnl=None)
        bets.append(b)
        journal_add(j, "PARI", b, b["pourquoi"], -mise)
        out.append(f"PLACÉ   {b['id']} {b['evenement']} · {b['selection']} @ {b['cote']} — mise {mise} €, gain potentiel {b['gain_potentiel']} €")
    save("bets.json", bets); save("journal.json", j)
    snapshot()
    print("\n".join(out))


def settle(bid, res, detail, cloture=None):
    res = {"gagné": "gagne", "remboursé": "rembourse"}.get(res, res)
    assert res in ("gagne", "perdu", "rembourse"), "résultat : gagne | perdu | rembourse"
    bets, j = load("bets.json", []), load("journal.json", [])
    b = next(x for x in bets if x["id"] == bid)
    assert b["statut"] == "en_cours", f"{bid} déjà réglé"
    retour = b["retour_potentiel"] if res == "gagne" else b["mise"] if res == "rembourse" else 0.0
    b.update(statut=res, resultat=detail, regle_le=now(), pnl=round(retour - b["mise"], 2),
             cote_cloture=float(cloture) if cloture else None)
    journal_add(j, {"gagne": "GAGNÉ", "perdu": "PERDU", "rembourse": "REMBOURSÉ"}[res], b, detail, round(retour, 2), b["pnl"])
    save("bets.json", bets); save("journal.json", j)
    snapshot()
    print(f"{bid} → {res} ({b['pnl']:+.2f} €)")


def snapshot():
    bets = load("bets.json", [])
    c = compte(bets)
    eq = load("equity.json", [])
    t = now()
    eq.append(dict(at=t, bankroll=c["bankroll"], dispo=c["dispo"], en_jeu=c["en_jeu"]))
    save("equity.json", eq)
    dec = c["decides"]
    save("state.json", dict(
        capital_initial=CAPITAL_INITIAL, debut=DEBUT, fin=FIN, maj=t, bankroll=c["bankroll"], disponible=c["dispo"],
        en_jeu=c["en_jeu"], pnl=c["pnl"], perf=round(c["pnl"] / CAPITAL_INITIAL, 4),
        roi=round(c["pnl"] / c["mises_reglees"], 4) if c["mises_reglees"] else None,
        paris=len(bets), en_cours=len(c["en_cours"]), regles=len(c["regle"]),
        gagnes=sum(1 for b in dec if b["statut"] == "gagne"), perdus=sum(1 for b in dec if b["statut"] == "perdu"),
        reussite=round(sum(1 for b in dec if b["statut"] == "gagne") / len(dec), 4) if dec else None,
        cote_moyenne=round(sum(b["cote"] for b in bets) / len(bets), 2) if bets else None,
        mise_totale=round(sum(b["mise"] for b in bets), 2),
        jours_restants=max(0, (date.fromisoformat(FIN) - date.fromisoformat(t[:10])).days),
    ))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    if cmd == "place":
        place(sys.argv[2])
    elif cmd == "settle":
        settle(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "", sys.argv[5] if len(sys.argv) > 5 else None)
    else:
        snapshot()
