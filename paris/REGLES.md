# Studio paris sportifs — règles (test fictif)

**Capital** : 1 000 € virtuels. **Période** : 30 octobre 2026 → 31 janvier 2027. **Bookmaker de référence** : Betclic (cotes relevées sur betclic.fr ou, à défaut, la cote Betclic affichée par un comparateur, avec l'heure du relevé). Aucun argent réel, aucun pari passé.

**Sports** : football, tennis, basket, rugby.

## Quand on parie
- Seulement après recherche : forme, blessures et absences, compositions probables, calendrier et fatigue, confrontations, enjeu, météo si utile, stats avancées (xG, classements, surfaces), avis d'experts, et cotes des autres bookmakers pour repérer les écarts.
- Proba estimée **avant** de regarder la cote. On parie si **proba × cote ≥ 1,05** (5 % d'avantage).
- Simples : cote entre **1,30 et 5,00**. Un seul pari simple par match.
- Combinés : **2 ou 3 sélections**, chacune avec proba ≥ 60 % et de la valeur, mise ≤ 1 % de la bankroll, **10 % de la bankroll maximum par semaine** en combinés.

## Combien on mise
- Kelly fractionné : 25 % de Kelly × confiance (×0,5 / ×1 / ×1,25), plafonné à **3 %** de la bankroll pour un simple, **1 %** pour un combiné. Mise minimale 2 €.
- **25 % de la bankroll en jeu au maximum** à tout moment.
- C'est `scripts/ledger.py` qui calcule les mises et refuse ce qui sort des règles.

## Règlement
- Résultat vérifié sur deux sources (site officiel de la compétition, presse sportive, résultats en direct).
- Match annulé ou reporté au-delà des règles Betclic : remboursé. Abandon au tennis : selon les règles Betclic.
- On note la cote de clôture quand on la trouve (pour mesurer si on a pris une bonne cote).

## Indicateurs
P&L, performance sur capital, ROI (P&L / mises réglées), taux de réussite, cote moyenne, résultats par sport, type de pari, tranche de cote et niveau de confiance.
