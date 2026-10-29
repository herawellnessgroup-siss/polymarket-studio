# polymarket-studio

Veille et analyse des marchés Polymarket, en **lecture seule**. Aucun ordre passé, aucun argent réel.

## Ce qui tourne

Toutes les heures (GitHub Actions, `.github/workflows/collect.yml`), `scripts/collect.py` :

1. lit les 100 marchés ouverts les plus échangés sur l'API publique Gamma ;
2. note chaque marché de A à E (liquidité, volume 24 h, accélération du volume, mouvement de cote, zone de prix) et lui donne un niveau de risque (durée, cote extrême, volatilité, écart achat/vente, liquidité, règles de résolution, aléa sportif) ;
3. archive l'instantané dans `data/history/AAAA-MM-JJ.jsonl` ;
4. tient un **portefeuille fictif** : une mise virtuelle sur le favori de chaque marché qui passe en A ou B (100 $ si risque faible, 50 $ modéré, 25 $ élevé), soldée quand Polymarket tranche.

## Fichiers produits

- `data/latest.json` : dernier état noté
- `data/history/` : un fichier par jour, une ligne par marché et par heure
- `data/paper/positions.json` : chaque pari fictif, son prix d'entrée et son résultat
- `data/paper/summary.json` : bilan (positions, gagnées, P&L, ROI)

## Limites

- La note dit où regarder, pas qui va gagner. Elle doit faire ses preuves sur le portefeuille fictif.
- Les frais et le glissement de prix ne sont pas comptés.
- Ce dépôt ne conseille personne et ne parie pas.
