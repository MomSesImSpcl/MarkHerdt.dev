#!/usr/bin/env python3
"""
Rogue Deck – A/B test plan and analysis: "Show expected payback in the Rogue shop"

Everything the case study page shows comes from this script:

  1. Baseline        real playtest logs (6 of 266 Rogue purchases were Common)
  2. Power           purchases and players needed per group, adjusted for clustering
  3. Duration        how long the test has to run with the assumed traffic
  4. Simulation      a SIMULATED experiment (the game is not live yet), so the
                     analysis pipeline can be shown end to end
  5. Analysis        sample ratio check, primary KPI with a cluster-robust
                     confidence interval and a player-level bootstrap,
                     guardrails, novelty check
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
LOG_PURCHASES = 266
LOG_COMMON_PURCHASES = 6
LOG_PLAYER_MATCHES = 10 * 2 + 10 * 4  # 10 two-player + 10 four-player matches
COMMON_OFFER_SHARE = 8 / 15           # rarity weights 8/4/2/1 -> 53.3% of offers

# ---------------------------------------------------------------------------
# Test design (decided before the test starts)
# ---------------------------------------------------------------------------
ALPHA = 0.05                 # two-sided, primary KPI
POWER = 0.80
GUARDRAIL_ALPHA = 0.05       # one-sided non-inferiority checks (90% CI)
MDE_ABS = 0.015              # smallest change worth acting on: +1.5 pp Common share
MIN_DAYS = 14                # two full weekly cycles, and room to see novelty fade

# Guardrails: (name, direction, margin). Direction "max_increase" / "max_decrease"
# is relative (fraction of control); "abs_band" / "abs_drop" are absolute.
GUARDRAILS = {
    "match_minutes": ("Match length", "max_increase", 0.05),
    "final_score": ("Average final score", "max_decrease", 0.05),
    "rogue_spend": ("Points spent on Rogue effects", "abs_band", 0.03),
    "d7": ("D7 retention (new players)", "abs_drop", 0.03),
}

# ---------------------------------------------------------------------------
# Assumptions (NOT measured – a soft-launch scale game)
# ---------------------------------------------------------------------------
UNIQUE_PLAYERS_14D = 24_000  # unique players who open the Rogue shop in 14 days
NEW_PLAYERS_PER_DAY = 600    # installs per day
MATCHES_PER_PLAYER = 6.0     # mean matches per player in the 14-day window
ICC = 0.05                   # correlation of Common buys within one player
D7_BASE = 0.15               # D7 retention of new players
MATCH_MIN_MEAN, MATCH_MIN_SD = 15.0, 4.0
SCORE_MEAN, SCORE_SD = 300.0, 120.0
SPEND_MEAN, SPEND_SD = 0.30, 0.08

# The "true" effects used by the SIMULATION (unknown in a real test)
SIM_COMMON_CONTROL = 0.023
SIM_COMMON_VARIANT = 0.040
SIM_NOVELTY = (1.08, 0.94)   # variant effect multiplier in week 1 / week 2
SIM_MATCH_MIN_LIFT = 0.017   # +1.7% (players read the payback line)
SIM_SCORE_LIFT = -0.012
SIM_SPEND_SHIFT = -0.008     # cheaper Commons -> slightly less spent
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
    """Player-level bootstrap of the difference in Common share (B - A)."""
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
        skill = rng.gauss(0, 0.5)  # player-level offset for score / length
        rec = {"arm": arm, "y": [0, 0], "n": [0, 0], "matches": matches,
               "match_minutes": 0.0, "final_score": 0.0, "rogue_spend": 0.0}
        for _ in range(matches):
            week = 0 if rng.random() < 0.5 else 1
            p = p_common
            if arm == "B":
                # novelty: effect a bit larger in week 1, smaller in week 2
                base = p_common * SIM_COMMON_CONTROL / SIM_COMMON_VARIANT
                p = base + (p_common - base) * SIM_NOVELTY[week]
            buys = poisson(LOG_PURCHASES / LOG_PLAYER_MATCHES, rng)
            commons = sum(1 for _ in range(buys) if rng.random() < p)
            rec["y"][week] += commons
            rec["n"][week] += buys
            minutes = rng.gauss(MATCH_MIN_MEAN + skill, MATCH_MIN_SD)
            score = rng.gauss(SCORE_MEAN * (1 + 0.2 * skill), SCORE_SD)
            spend = rng.gauss(SPEND_MEAN, SPEND_SD)
            if arm == "B":
                minutes *= 1 + SIM_MATCH_MIN_LIFT
                score *= 1 + SIM_SCORE_LIFT
                spend += SIM_SPEND_SHIFT
            rec["match_minutes"] += minutes
            rec["final_score"] += score
            rec["rogue_spend"] += spend
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
    p0 = LOG_COMMON_PURCHASES / LOG_PURCHASES
    per_match = LOG_PURCHASES / LOG_PLAYER_MATCHES
    print("1. BASELINE (real playtest logs)")
    print(f"   Common share of Rogue purchases: {LOG_COMMON_PURCHASES}/{LOG_PURCHASES} = {pct(p0, 2)}")
    print(f"   Common share of offers:          {pct(COMMON_OFFER_SHARE)}")
    print(f"   Purchases per player per match:  {per_match:.1f}")
    out["baseline"] = {"p0": p0, "offer_share": COMMON_OFFER_SHARE, "per_match": per_match}

    # 2. Power -----------------------------------------------------------------
    n_iid = n_two_proportions(p0, p0 + MDE_ABS)
    m = MATCHES_PER_PLAYER * per_match          # purchases per player in window
    deff = 1 + (m - 1) * ICC
    n_purch = math.ceil(n_iid * deff)
    n_players = math.ceil(n_purch / m)
    print("\n2. SAMPLE SIZE (primary KPI)")
    print(f"   MDE: {pp(MDE_ABS, 1)} ({pct(p0, 1)} -> {pct(p0 + MDE_ABS, 1)}), alpha {ALPHA}, power {POWER}")
    print(f"   Purchases per group if independent: {n_iid:,}")
    print(f"   Purchases per player in 14 days:    {m:.1f}")
    print(f"   Design effect 1 + (m-1)*ICC:         {deff:.2f}  (ICC {ICC})")
    print(f"   Purchases per group, clustered:      {n_purch:,}")
    print(f"   Players per group:                   {n_players:,}")

    per_arm_players = UNIQUE_PLAYERS_14D / 2
    eff_n = per_arm_players * m / deff
    mde_reach = mde_two_proportions(p0, eff_n)
    d7_n = NEW_PLAYERS_PER_DAY * 7 / 2
    d7_need_1pp = n_noninferiority(D7_BASE, 0.01)
    d7_reach = ni_margin(D7_BASE, d7_n)
    print("\n   Guardrail power (D7 retention, one-sided non-inferiority)")
    print(f"   New players per group with a D7 in the window: {d7_n:,.0f}")
    print(f"   Needed to rule out a 1 pp drop:                 {d7_need_1pp:,}")
    print(f"   Smallest drop this test can rule out:           {pp(-d7_reach, 1)}")
    out["power"] = {"mde": MDE_ABS, "n_iid": n_iid, "m": m, "deff": deff,
                    "n_purchases": n_purch, "n_players": n_players,
                    "mde_reach": mde_reach, "d7_n": d7_n,
                    "d7_need_1pp": d7_need_1pp, "d7_reach": d7_reach}

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
    print(f"   Purchases: A {sum(na):,} / B {sum(nb):,}")
    print(f"   Common share  A {pct(ra, 2)}   B {pct(rb, 2)}")
    print(f"   Difference    {pp(diff)}  (95% CI {pp(ci[0])} to {pp(ci[1])}), p {"< 0.001" if p_val < 0.001 else f"= {p_val:.3f}"}")
    print(f"   Relative lift {diff / ra:+.0%}")
    print(f"   Bootstrap 95% CI ({BOOTSTRAP_REPS} player resamples): {pp(boot[0])} to {pp(boot[1])}")
    print(f"   Observed design effect: {obs_deff:.2f}")
    out["result"] = {"nA": nA, "nB": nB, "chi": chi, "p_srm": p_srm,
                     "purchA": sum(na), "purchB": sum(nb), "ra": ra, "rb": rb,
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
    print("\n   Guardrails (90% CI vs. margin)")
    guard = {}
    for key, (label, kind, margin) in GUARDRAILS.items():
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
        lo, hi = d - zg * se_g, d + zg * se_g
        if kind == "max_increase":
            ok = hi < margin * ma
            shown = (d / ma, lo / ma, hi / ma)
            rule = f"increase < {margin:.0%}"
        elif kind == "max_decrease":
            ok = lo > -margin * ma
            shown = (d / ma, lo / ma, hi / ma)
            rule = f"decrease < {margin:.0%}"
        elif kind == "abs_band":
            ok = lo > -margin and hi < margin
            shown = (d, lo, hi)
            rule = f"within ±{margin * 100:.0f} pp"
        else:
            ok = lo > -margin
            shown = (d, lo, hi)
            rule = f"drop < {margin * 100:.0f} pp"
        rel = kind.startswith("max")
        fmt = (lambda v: f"{v:+.1%}") if rel else (lambda v: pp(v, 1))
        print(f"   {label:32s} A {ma:8.3f}  B {mb:8.3f}  {fmt(shown[0])}"
              f"  (90% CI {fmt(shown[1])} to {fmt(shown[2])})  rule: {rule}  -> {'pass' if ok else 'FAIL'}")
        guard[key] = {"label": label, "a": ma, "b": mb, "delta": shown[0],
                      "lo": shown[1], "hi": shown[2], "relative": rel,
                      "rule": rule, "pass": ok}
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
