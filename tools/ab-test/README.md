# Rogue Deck – A/B test: showing expected payback in the Rogue shop

Plan and analysis code for the A/B test described on
[markherdt.dev/games/rogue-deck/ab-test.html](https://markherdt.dev/games/rogue-deck/ab-test.html).

**Only the baseline is real data.** Rogue Deck is not live yet, so the experiment
itself is **simulated**: traffic, retention, intra-player correlation and the
effect sizes are assumptions set at the top of `ab_test.py`. The point is to show
the full pipeline (power calculation, assignment check, analysis, guardrails and
the decision) so it can be run unchanged on real event logs later.

## What the script does

| Step | What it computes |
|---|---|
| 1. Baseline | Common share of Rogue purchases from the playtest logs: 6 of 266 = 2.26% |
| 2. Sample size | Two-proportion power calculation, inflated by the design effect `1 + (m − 1) · ICC` because one player makes many purchases |
| 2b. Guardrail power | How large a D7 retention drop the test can rule out with the expected number of new players |
| 3. Duration | Days needed, with a minimum of 14 days and whole weeks |
| 4. Simulation | Players assigned 50/50, per-player Common preference from a Beta distribution (gives the assumed ICC), novelty effect in week 1 |
| 5. Analysis | Sample ratio mismatch (chi-square), Common share with a cluster-robust delta-method CI, player-level bootstrap CI, week 1 vs week 2, four guardrails with non-inferiority margins |
| 6. Decision | Ship only if assignment is healthy, the primary CI is above 0 and every guardrail passes |

## Run it

```bash
python ab_test.py                  # default seed 42 (the numbers on the website)
python ab_test.py --seed 7         # another simulated run
python ab_test.py --json out.json  # also write every number as JSON
```

Python 3.8+, standard library only. Runs in a few seconds.
