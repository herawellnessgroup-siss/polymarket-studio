# polymarket-studio

Veille et analyse des marchés Polymarket, en **lecture seule**. Aucun ordre passé, aucun argent réel.

## Ce qui tourne

Toutes les heures (GitHub Actions, `.github/workflows/collect.yml`), `scripts/collect.py` :

1. lit les 100 marchés ouverts les plus échangés sur l'API publique Gamma ;
2. note chaque marché de A à E (liquidité, volume 24 h, accélération du volume, mouvement de cote, zone de prix) et lui donne un niveau de risque (durée, cote extrême, volatilité, écart achat/vente, liquidité, règles de résolution, aléa sportif) ;
3. archive l'instantané dans `data/history/AAAA-MM-JJ.jsonl` ;
4. fait tourner un **broker fictif** (`scripts/broker.py`) : 1 000 $ virtuels du 30 octobre au 30 novembre 2026. Il entre sur les marchés notés A ou B qui se tranchent pendant le test, dimensionne chaque mise selon le risque, sort en prise de bénéfice ou en stop-loss, et écrit chaque décision et son pourquoi dans un journal. Les règles exactes sont en tête de `scripts/broker.py`.

## Fichiers produits

- `data/latest.json` : dernier état noté
- `data/history/` : un fichier par jour, une ligne par marché et par heure
- `data/paper/state.json` : capital, cash, valeur, P&L réalisé et latent
- `data/paper/positions.json` : chaque position, son pourquoi, son prix d'entrée, sa valeur et son résultat
- `data/paper/journal.json` : chaque entrée, sortie et résolution, horodatée et motivée
- `data/paper/equity.json` : valeur du portefeuille heure par heure

## Limites

- La note dit où regarder, pas qui va gagner. Elle doit faire ses preuves sur le portefeuille fictif.
- Les frais et le glissement de prix ne sont pas comptés.
- Ce dépôt ne conseille personne et ne parie pas.
