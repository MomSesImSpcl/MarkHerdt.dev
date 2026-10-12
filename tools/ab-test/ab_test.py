#!/usr/bin/env python3
"""
Rogue Deck A/B test plan and analysis: "Show expected payback in the Rogue shop"

Analysis code for the test planned on the A/B test page:

  1. Baseline        real playtest logs (6 of ~426 Common offers were bought,
                     counted on turns where the player bought a Rogue effect)
  2. Power           Common offers and players needed per group, adjusted for clustering
  3. Duration        how long the test has to run with the assumed traffic
  4. Simulation      a SIMULATED experiment (the game is not live yet), so the
                     analysis pipeline can be shown end to end
  5. Analysis        sample ratio check, primary KPI with a cluster-robust
                     confidence interval and a player-level bootstrap,
                     guardrails (final score, D7 retention), novelty check
  6. Decision        ship / don't ship, following the pre-registered rules

Only the baseline numbers are real. Traffic, retention, intra-player
correlation and the simulated effect sizes are assumptions, set below.

Standard library only. Usage:
    python ab_test.py                 # default seed, prints the full report
    python ab_test.py --seed 7        # another simulated run
    python ab_test.py --json out.json # also write all numbers as JSON
"""
import argparse
import json
import math
import random
from statistics import NormalDist

N = NormalDist()

# ---------------------------------------------------------------------------
# 1. Baseline from the real playtest logs (20 matches, 60 player-matches)
# ---------------------------------------------------------------------------
LOG_PURCHASE_TURNS = 266              # turns on which a player bought a Rogue effect
LOG_COMMON_PURCHASES = 6
LOG_PLAYER_MATCHES = 10 * 2 + 10 * 4  # 10 two-player + 10 four-player matches
OFFERS_PER_TURN = 3
COMMON_OFFER_SHARE = 8 / 15           # rarity weights 8/4/2/1 -> 53.3% of offers
# Common offers seen on purchase turns: 266 x 3 x 8/15 = ~426
LOG_COMMON_OFFERS = round(LOG_PURCHASE_TURNS * OFFERS_PER_TURN * COMMON_OFFER_SHARE)

# ---------------------------------------------------------------------------
# Test design (decided before the test starts)
# ---------------------------------------------------------------------------
ALPHA = 0.05                 # two-sided, primary KPI
POWER = 0.80
GUARDRAIL_ALPHA = 0.05       # one-sided guardrail checks (90% CI)
MDE_ABS = 0.015              # smallest change worth acting on: +1.5 pp Common purchase rate
MIN_DAYS = 14                # two full weekly cycles, and room to see novelty fade

# Guardrails: (name, margin). The margin is a relative drop (fraction of control).
# A guardrail fails only if B is clearly worse than A by more than the margin,
# i.e. the whole 90% CI of the relative change lies below -margin.
GUARDRAILS = {
    "final_score": ("Average final score", 0.05),
    "d7": ("D7 retention (new players)", 0.05),
}

# ---------------------------------------------------------------------------
# Assumptions (NOT measured – a soft-launch scale game)
# ---------------------------------------------------------------------------
UNIQUE_PLAYERS_14D = 24_000  # unique players who open the Rogue shop in 14 days
NEW_PLAYERS_PER_DAY = 600    # installs per day
MATCHES_PER_PLAYER = 6.0     # mean matches per player in the 14-day window
ICC = 0.05                   # correlation of Common buys within one player
D7_BASE = 0.15               # D7 retention of new players
SCORE_MEAN, SCORE_SD = 300.0, 120.0

# The "true" effects used by the SIMULATION (unknown in a real test)
SIM_COMMON_CONTROL = 0.014   # chance a Common offer is bought (baseline 1.4%)
SIM_COMMON_VARIANT = 0.030
SIM_NOVELTY = (1.08, 0.94)   # variant effect multiplier in week 1 / week 2
SIM_SCORE_LIFT = -0.012
SIM_D7_SHIFT = -0.003

BOOTSTRAP_REPS = 1000


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------
def z(p):
    return N.inv_cdf(p)


def n_two_proportions(p1, p2, alpha=ALPHA, power=POWER):
    """Observations per group for a two-sided two-proportion z-test."""
    pbar = (p1 + p2) / 2
    a = z(1 - alpha / 2) * math.sqrt(2 * pbar * (1 - pbar))
    b = z(power) * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    return math.ceil((a + b) ** 2 / (p2 - p1) ** 2)


def mde_two_proportions(p1, n, alpha=ALPHA, power=POWER):
    """Smallest absolute lift detectable with n observations per group."""
    lo, hi = 1e-6, 1 - p1 - 1e-6
    for _ in range(80):
        mid = (lo + hi) / 2
        if n_two_proportions(p1, p1 + mid, alpha, power) > n:
            lo = mid
        else:
            hi = mid
    return hi


def n_noninferiority(p, margin, alpha=GUARDRAIL_ALPHA, power=POWER):
    """Players per group to show a proportion did not drop by more than margin."""
    return math.ceil((z(1 - alpha) + z(power)) ** 2 * 2 * p * (1 - p) / margin ** 2)


def ni_margin(p, n, alpha=GUARDRAIL_ALPHA, power=POWER):
    """Smallest drop a non-inferiority test with n per group can rule out."""
    return (z(1 - alpha) + z(power)) * math.sqrt(2 * p * (1 - p) / n)


def poisson(lam, rng):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def ratio_and_se(ys, ns):
    """Ratio metric sum(y)/sum(n) with a cluster-robust (delta method) SE.
    Each player is one cluster, so repeated purchases by the same player
    are not treated as independent."""
    k = len(ys)
    Y, M = sum(ys), sum(ns)
    r = Y / M
    var = sum((y - r * n) ** 2 for y, n in zip(ys, ns)) / M ** 2 * k / (k - 1)
    return r, math.sqrt(var)


def bootstrap_diff(a, b, rng, reps=BOOTSTRAP_REPS):
    """Player-level bootstrap of the difference in Common purchase rate (B - A)."""
    ya, na = a
    yb, nb = b
    ka, kb = len(ya), len(yb)
    ia, ib = range(ka), range(kb)
    diffs = []
    for _ in range(reps):
        sa = rng.choices(ia, k=ka)
        sb = rng.choices(ib, k=kb)
        ra = sum(map(ya.__getitem__, sa)) / sum(map(na.__getitem__, sa))
        rb = sum(map(yb.__getitem__, sb)) / sum(map(nb.__getitem__, sb))
        diffs.append(rb - ra)
    diffs.sort()
    return diffs[int(0.025 * reps)], diffs[int(0.975 * reps) - 1]


# ---------------------------------------------------------------------------
# Simulation of the experiment
# ---------------------------------------------------------------------------
def simulate(seed):
    rng = random.Random(seed)
    conc = 1 / ICC - 1  # Beta(a, b) with a + b = conc gives this ICC
    players = []
    for pid in range(UNIQUE_PLAYERS_14D):
        arm = "B" if rng.random() < 0.5 else "A"  # stands in for hash(player_id) % 2
        mean = SIM_COMMON_VARIANT if arm == "B" else SIM_COMMON_CONTROL
        p_common = rng.betavariate(mean * conc, (1 - mean) * conc)
        # how often the player plays in the window (at least one match)
        matches = 1 + poisson(MATCHES_PER_PLAYER - 1, rng)
        skill = rng.gauss(0, 0.5)  # player-level offset for score
        rec = {"arm": arm, "y": [0, 0], "n": [0, 0], "matches": matches,
               "final_score": 0.0}
        for _ in range(matches):
            week = 0 if rng.random() < 0.5 else 1
            p = p_common
            if arm == "B":
                # novelty: effect a bit larger in week 1, smaller in week 2
                base = p_common * SIM_COMMON_CONTROL / SIM_COMMON_VARIANT
                p = base + (p_common - base) * SIM_NOVELTY[week]
            # turns with a Rogue purchase; each shows 3 offers, some of them Common
            for _ in range(poisson(LOG_PURCHASE_TURNS / LOG_PLAYER_MATCHES, rng)):
                k = sum(1 for _ in range(OFFERS_PER_TURN) if rng.random() < COMMON_OFFER_SHARE)
                if k:
                    # one purchase per turn: a Common is bought with chance 1-(1-p)^k
                    rec["y"][week] += 1 if rng.random() < 1 - (1 - p) ** k else 0
                    rec["n"][week] += k
            score = rng.gauss(SCORE_MEAN * (1 + 0.2 * skill), SCORE_SD)
            if arm == "B":
                score *= 1 + SIM_SCORE_LIFT
            rec["final_score"] += score
        # new players whose day 7 falls inside the window
        rec["new"] = rng.random() < NEW_PLAYERS_PER_DAY * 7 / UNIQUE_PLAYERS_14D
        if rec["new"]:
            d7 = D7_BASE + (SIM_D7_SHIFT if arm == "B" else 0)
            rec["d7"] = 1 if rng.random() < d7 else 0
        players.append(rec)
    return players, rng


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def pct(x, d=1):
    return f"{100 * x:.{d}f}%"


def pp(x, d=2):
    return f"{100 * x:+.{d}f} pp"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--json", help="write all numbers to this JSON file")
    args = ap.parse_args()
    out = {}

    # 1. Baseline -----------------------------------------------------------
    p0 = LOG_COMMON_PURCHASES / LOG_COMMON_OFFERS
    per_match = LOG_PURCHASE_TURNS / LOG_PLAYER_MATCHES
    print("1. BASELINE (real playtest logs)")
    print(f"   Turns with a Rogue purchase:          {LOG_PURCHASE_TURNS}")
    print(f"   Common offers on those turns:         ~{LOG_COMMON_OFFERS} ({OFFERS_PER_TURN} offers x {pct(COMMON_OFFER_SHARE)})")
    print(f"   Common purchases per Common offer:    {LOG_COMMON_PURCHASES}/{LOG_COMMON_OFFERS} = {pct(p0, 2)}")
    print(f"   Purchase turns per player per match:  {per_match:.1f}")
    out["baseline"] = {"p0": p0, "common_offers": LOG_COMMON_OFFERS,
                       "offer_share": COMMON_OFFER_SHARE, "per_match": per_match}

    # 2. Power -----------------------------------------------------------------
    n_iid = n_two_proportions(p0, p0 + MDE_ABS)
    m = MATCHES_PER_PLAYER * per_match * OFFERS_PER_TURN * COMMON_OFFER_SHARE  # Common offers per player
    deff = 1 + (m - 1) * ICC
    n_purch = math.ceil(n_iid * deff)
    n_players = math.ceil(n_purch / m)
    print("\n2. SAMPLE SIZE (primary KPI)")
    print(f"   MDE: {pp(MDE_ABS, 1)} ({pct(p0, 1)} -> {pct(p0 + MDE_ABS, 1)}), alpha {ALPHA}, power {POWER}")
    print(f"   Common offers per group if independent:  {n_iid:,}")
    print(f"   Common offers per player in 14 days:    {m:.1f}")
    print(f"   Design effect 1 + (m-1)*ICC:             {deff:.2f}  (ICC {ICC})")
    print(f"   Common offers per group, clustered:      {n_purch:,}")
    print(f"   Players per group:                       {n_players:,}")

    per_arm_players = UNIQUE_PLAYERS_14D / 2
    eff_n = per_arm_players * m / deff
    mde_reach = mde_two_proportions(p0, eff_n)
    d7_n = NEW_PLAYERS_PER_DAY * 7 / 2
    d7_margin = GUARDRAILS["d7"][1] * D7_BASE   # 5% relative = 0.75 pp
    d7_need = n_noninferiority(D7_BASE, d7_margin)
    d7_reach = ni_margin(D7_BASE, d7_n)
    print("\n   Guardrail precision (D7 retention)")
    print(f"   New players per group with a D7 in the window: {d7_n:,.0f}")
    print(f"   Needed to detect a {GUARDRAILS['d7'][1]:.0%} drop ({pp(-d7_margin)}):      {d7_need:,}")
    print(f"   Smallest drop this test reliably detects:       {pp(-d7_reach, 1)} ({-d7_reach / D7_BASE:+.0%})")
    out["power"] = {"mde": MDE_ABS, "n_iid": n_iid, "m": m, "deff": deff,
                    "n_common_offers": n_purch, "n_players": n_players,
                    "mde_reach": mde_reach, "d7_n": d7_n,
                    "d7_need": d7_need, "d7_reach": d7_reach}

    # 3. Duration --------------------------------------------------------------
    players_per_day = UNIQUE_PLAYERS_14D / 14 / 2  # rough: new uniques per group
    days_needed = math.ceil(n_players / players_per_day)
    days = max(days_needed, MIN_DAYS)
    days = math.ceil(days / 7) * 7
    print("\n3. DURATION")
    print(f"   Days to reach the primary sample: {days_needed}")
    print(f"   Planned duration (min {MIN_DAYS}, full weeks): {days} days")
    print(f"   With the full traffic the primary KPI can detect {pp(mde_reach)}")
    out["duration"] = {"days_needed": days_needed, "days": days}

    # 4./5. Simulated experiment + analysis ------------------------------------
    players, rng = simulate(args.seed)
    A = [p for p in players if p["arm"] == "A"]
    B = [p for p in players if p["arm"] == "B"]
    nA, nB = len(A), len(B)
    exp = (nA + nB) / 2
    chi = (nA - exp) ** 2 / exp + (nB - exp) ** 2 / exp
    p_srm = math.erfc(math.sqrt(chi / 2))
    print("\n4. SIMULATED EXPERIMENT (not real data)")
    print(f"   Players: A {nA:,} / B {nB:,}   SRM chi2 {chi:.2f}, p = {p_srm:.2f}"
          f" -> {'OK' if p_srm > 0.001 else 'STOP: assignment broken'}")

    def arm_ratio(ps, weeks=(0, 1)):
        ys = [sum(p["y"][w] for w in weeks) for p in ps]
        ns = [sum(p["n"][w] for w in weeks) for p in ps]
        keep = [(y, n) for y, n in zip(ys, ns) if n > 0]
        return [k[0] for k in keep], [k[1] for k in keep]

    ya, na = arm_ratio(A)
    yb, nb = arm_ratio(B)
    ra, sa = ratio_and_se(ya, na)
    rb, sb = ratio_and_se(yb, nb)
    diff = rb - ra
    se = math.sqrt(sa ** 2 + sb ** 2)
    zc = z(1 - ALPHA / 2)
    ci = (diff - zc * se, diff + zc * se)
    p_val = 2 * (1 - N.cdf(abs(diff / se)))
    obs_deff = sa ** 2 / (ra * (1 - ra) / sum(na))
    boot = bootstrap_diff((ya, na), (yb, nb), rng)
    print("\n5. ANALYSIS")
    p_txt = "< 0.001" if p_val < 0.001 else f"= {p_val:.3f}"
    print(f"   Common offers: A {sum(na):,} / B {sum(nb):,}")
    print(f"   Common purchase rate  A {pct(ra, 2)}   B {pct(rb, 2)}")
    print(f"   Difference    {pp(diff)}  (95% CI {pp(ci[0])} to {pp(ci[1])}), p {p_txt}")
    print(f"   Relative lift {diff / ra:+.0%}")
    print(f"   Bootstrap 95% CI ({BOOTSTRAP_REPS} player resamples): {pp(boot[0])} to {pp(boot[1])}")
    print(f"   Observed design effect: {obs_deff:.2f}")
    out["result"] = {"nA": nA, "nB": nB, "chi": chi, "p_srm": p_srm,
                     "offersA": sum(na), "offersB": sum(nb), "ra": ra, "rb": rb,
                     "diff": diff, "ci": ci, "p": p_val, "rel": diff / ra,
                     "boot": boot, "obs_deff": obs_deff,
                     "ciA": (ra - zc * sa, ra + zc * sa), "ciB": (rb - zc * sb, rb + zc * sb)}

    # novelty: week 1 vs week 2
    weeks = []
    for w in (0, 1):
        ya_w, na_w = arm_ratio(A, (w,))
        yb_w, nb_w = arm_ratio(B, (w,))
        ra_w, sa_w = ratio_and_se(ya_w, na_w)
        rb_w, sb_w = ratio_and_se(yb_w, nb_w)
        d_w = rb_w - ra_w
        se_w = math.sqrt(sa_w ** 2 + sb_w ** 2)
        weeks.append({"ra": ra_w, "rb": rb_w, "diff": d_w,
                      "ci": (d_w - zc * se_w, d_w + zc * se_w)})
        print(f"   Week {w + 1}: A {pct(ra_w, 2)}  B {pct(rb_w, 2)}  diff {pp(d_w)}"
              f"  (95% CI {pp(d_w - zc * se_w)} to {pp(d_w + zc * se_w)})")
    out["weeks"] = weeks

    # guardrails
    zg = z(1 - GUARDRAIL_ALPHA)  # 90% two-sided CI = one-sided 95% bound
    print("\n   Guardrails (90% CI of the relative change vs. margin)")
    guard = {}
    for key, (label, margin) in GUARDRAILS.items():
        if key == "d7":
            xa = [p["d7"] for p in A if p["new"]]
            xb = [p["d7"] for p in B if p["new"]]
            ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
            se_g = math.sqrt(ma * (1 - ma) / len(xa) + mb * (1 - mb) / len(xb))
        else:
            ma, sea = ratio_and_se([p[key] for p in A], [p["matches"] for p in A])
            mb, seb = ratio_and_se([p[key] for p in B], [p["matches"] for p in B])
            se_g = math.sqrt(sea ** 2 + seb ** 2)
        d = mb - ma
        lo, hi = (d - zg * se_g) / ma, (d + zg * se_g) / ma
        ok = hi >= -margin   # fails only if clearly down by more than the margin
        rule = f"fail if clearly down > {margin:.0%}"
        print(f"   {label:28s} A {ma:8.3f}  B {mb:8.3f}  {d / ma:+.1%}"
              f"  (90% CI {lo:+.1%} to {hi:+.1%})  rule: {rule}  -> {'pass' if ok else 'FAIL'}")
        guard[key] = {"label": label, "a": ma, "b": mb, "delta": d / ma,
                      "lo": lo, "hi": hi, "rule": rule, "pass": ok}
    out["guardrails"] = guard

    # 6. Decision ----------------------------------------------------------------
    primary_ok = ci[0] > 0
    srm_ok = p_srm > 0.001
    guards_ok = all(g["pass"] for g in guard.values())
    ship = primary_ok and srm_ok and guards_ok
    print("\n6. DECISION (pre-registered rules)")
    print(f"   Assignment healthy (SRM p > 0.001): {srm_ok}")
    print(f"   Primary CI lower bound > 0:         {primary_ok}")
    print(f"   All guardrails pass:                {guards_ok}")
    print(f"   -> {'SHIP with staged rollout and holdback' if ship else 'DO NOT SHIP'}")
    out["decision"] = {"ship": ship}

    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
