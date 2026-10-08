"""Rogue Deck – collection progress simulation (Monte Carlo).

Opens booster packs month by month for several player profiles and reports how
much of the collection each profile owns: all effect variants (any art) and all
artworks (every card in every art style).

Reproducible: same inputs + same --seed => same output.

Usage:
    python collection_sim.py                     # default profiles, 300 runs
    python collection_sim.py --runs 1000 --months 12
    python collection_sim.py --packs Casual=19.1 Regular=38.6 --csv out.csv

Inputs mirror the economy model (Google Sheet):
  * packs per month per profile  -> Profiles sheet, "TOTAL PACKS PER MONTH"
  * rarity weights 8/4/2/1         -> Pack Odds sheet (same as in-match Rogue offers)
  * art weights 90/8.9/1/0.1 %     -> Pack Odds sheet
  * pack layout: 1 Rogue card + 4 playing cards
"""
import argparse
import csv
import random
import statistics

RARITIES = ["Common", "Rare", "Epic", "Legendary"]
RARITY_WEIGHTS = [8, 4, 2, 1]
# Number of effect variants per rarity (current effect catalog)
CARD_VARIANTS = {"Common": 9, "Rare": 8, "Epic": 10, "Legendary": 8}    # 35 playing-card effect variants
ROGUE_VARIANTS = {"Common": 4, "Rare": 6, "Epic": 7, "Legendary": 9}    # 26 Rogue effect variants
ART_STYLES = ["Default", "Holo", "Full Art", "Alt Art"]
ART_WEIGHTS = [900, 89, 10, 1]                                          # 90% / 8.9% / 1% / 0.1%
PLAYING_CARDS = 52
CARDS_PER_PACK = 5      # slot 0 = Rogue card, slots 1-4 = playing cards

TOTAL_EFFECTS = sum(CARD_VARIANTS.values()) + sum(ROGUE_VARIANTS.values())         # 61
TOTAL_ARTWORKS = PLAYING_CARDS * len(ART_STYLES) + sum(ROGUE_VARIANTS.values()) * len(ART_STYLES)  # 312

DEFAULT_PACKS = {"Casual": 19.1, "Regular": 38.6, "Engaged": 69.6, "Hardcore": 88.7}


def roll_effect(rng, variants):
    rarity = rng.choices(RARITIES, RARITY_WEIGHTS)[0]
    return rarity, rng.randrange(variants[rarity])


def simulate_player(rng, packs_per_month, months):
    """Returns [(effect_share, artwork_share), ...] for each month."""
    effects, artworks, results, carry = set(), set(), [], 0.0
    for _ in range(months):
        carry += packs_per_month
        packs, carry = int(carry), carry - int(carry)   # fractional packs carry over to next month
        for _ in range(packs):
            for slot in range(CARDS_PER_PACK):
                art = rng.choices(ART_STYLES, ART_WEIGHTS)[0]
                if slot == 0:
                    rarity, i = roll_effect(rng, ROGUE_VARIANTS)
                    effects.add(("Rogue", rarity, i))
                    artworks.add(("Rogue", rarity, i, art))
                else:
                    rarity, i = roll_effect(rng, CARD_VARIANTS)
                    card = rng.randrange(PLAYING_CARDS)
                    effects.add(("Card", rarity, i))
                    artworks.add(("Card", card, art))
        results.append((len(effects) / TOTAL_EFFECTS, len(artworks) / TOTAL_ARTWORKS))
    return results


def percentile(values, p):
    values = sorted(values)
    k = (len(values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def run(profiles, runs, months, seed):
    rows = []
    for name, packs in profiles.items():
        sims = [simulate_player(random.Random(seed + r), packs, months) for r in range(runs)]
        for m in range(months):
            for metric, idx in (("effects", 0), ("artworks", 1)):
                vals = [s[m][idx] for s in sims]
                rows.append({
                    "profile": name, "packs_per_month": packs, "month": m + 1, "metric": metric,
                    "mean": statistics.mean(vals), "p10": percentile(vals, 0.10), "p90": percentile(vals, 0.90),
                })
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=300, help="simulated players per profile (default 300)")
    ap.add_argument("--months", type=int, default=6)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--packs", nargs="*", help="override profiles, e.g. Casual=19.1 Regular=38.6")
    ap.add_argument("--csv", help="write all results to this CSV file")
    a = ap.parse_args()
    profiles = dict(DEFAULT_PACKS)
    if a.packs:
        profiles = {k: float(v) for k, v in (p.split("=") for p in a.packs)}
    rows = run(profiles, a.runs, a.months, a.seed)
    print(f"{a.runs} runs per profile, seed {a.seed}. Mean [10th–90th percentile].")
    for metric in ("effects", "artworks"):
        print(f"\n{metric.upper()} owned")
        print("profile".ljust(10) + "".join(f"M{m+1}".rjust(16) for m in range(a.months)))
        for name in profiles:
            cells = [r for r in rows if r["profile"] == name and r["metric"] == metric]
            print(name.ljust(10) + "".join(f"{r['mean']:.0%} [{r['p10']:.0%}–{r['p90']:.0%}]".rjust(16) for r in cells))
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\nWrote {len(rows)} rows to {a.csv}")


if __name__ == "__main__":
    main()
