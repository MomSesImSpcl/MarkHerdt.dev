# Rogue Deck – Economy simulation

Monte Carlo simulation behind the **Collection progress** charts on the
[LiveOps & economy case study](https://markherdt.dev/games/rogue-deck/liveops.html).

It simulates players opening booster packs month by month and measures how much
of the collection they own:

- **Effects:** all 61 effect variants (35 playing-card + 26 Rogue), in any art style
- **Artworks:** all 312 artworks (52 playing cards × 4 art styles + 26 Rogue cards × 4 art styles)

Each profile is simulated 300 times. The output shows the **mean** and the
**10th–90th percentile range** (the unluckiest and luckiest 10% of players).

## Run it

Python 3.8+, no dependencies.

```bash
python collection_sim.py                          # default profiles
python collection_sim.py --runs 1000 --months 12  # more runs, longer horizon
python collection_sim.py --packs Casual=19.1 Regular=38.6 --csv results.csv
```

The same inputs and `--seed` always produce the same results.

## Inputs

| Input | Value | Source |
|---|---|---|
| Packs per month | Casual 19.1 · Regular 38.6 · Engaged 69.6 · Hardcore 88.7 | Economy model, *Profiles* sheet |
| Rarity weights | 8 / 4 / 2 / 1 | Same as the in-match Rogue offers |
| Art style chances | 90% / 8.9% / 1% / 0.1% | Economy model, *Pack Odds* sheet |
| Pack layout | 1 Rogue card + 4 playing cards | Design |

Economy model (Google Sheets):
https://docs.google.com/spreadsheets/d/1jcOW8E9k-_3IaDA458qoxKh_49oPYQluWO2pk144yH0/edit?usp=sharing

`results.csv` contains the output of the default run.

## Limitations

- Uses the current effect catalog; new effects lower all percentages.
- Packs per month are averages for typical players in each group.
- The pity system and crafting are not modeled.
