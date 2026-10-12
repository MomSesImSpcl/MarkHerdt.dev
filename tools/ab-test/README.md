# Rogue Deck A/B test: showing expected payback in the Rogue shop

Plan and analysis code for the A/B test described on
[markherdt.dev/games/rogue-deck/ab-test-plan.html](https://markherdt.dev/games/rogue-deck/ab-test-plan.html).

Only the baseline is real data. Rogue Deck isn't live yet, so the experiment
itself is simulated: traffic, retention, intra-player correlation and the
effect sizes are assumptions set at the top of `ab_test.py`. The point is to show
the whole pipeline (power calculation, assignment check, analysis, guardrails and
the decision) so it can be run unchanged on real event logs later.

## What the script does

| Step | What it computes |
|---|---|
| 1. Baseline | Common purchases per Common offer, counted on turns where the player bought a Rogue effect: 6 of ~426 = 1.4% (266 purchase turns × 3 offers × 8/15 Common) |
| 2. Sample size | Two-proportion power calculation, inflated by the design effect `1 + (m − 1) · ICC` because one player sees many Common offers |
| 2b. Guardrail precision | How large a D7 retention drop the test can reliably detect with the expected number of new players |
| 3. Duration | Days needed, with a minimum of 14 days and whole weeks |
| 4. Simulation | Players assigned 50/50, per-player Common preference from a Beta distribution (gives the assumed ICC), novelty effect in week 1 |
| 5. Analysis | Sample ratio mismatch (chi-square), Common purchase rate with a cluster-robust delta-method CI, player-level bootstrap CI, week 1 vs week 2, two guardrails: final score and D7 retention. A guardrail fails if B is clearly down by more than 5% (the whole 90% CI is below −5%) |
| 6. Decision | Ship only if assignment is healthy, the primary CI is above 0 and every guardrail passes |

## Run it

```bash
python ab_test.py                  # default seed 42
python ab_test.py --seed 7         # another simulated run
python ab_test.py --json out.json  # also write every number as JSON
```

Python 3.8+, standard library only. Runs in a few seconds.
