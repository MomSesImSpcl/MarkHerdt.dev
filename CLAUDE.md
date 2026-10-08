# CLAUDE.md

Portfolio site for Mark Herdt, live at https://markherdt.dev (GitHub Pages, served from `main`).
Goal: show his resume, games and work projects when applying for game design and programming roles. His main language is C#.

## Rules
- Push approved changes directly to `main`. No PRs. Discuss and agree on changes first.
- Use American spelling in all site copy.
- Never list Python as one of Mark's skills. The economy sim and A/B tool are Python, but he designed the models and used AI help for the scripts.
- Be critical, not agreeable. Keep sentences clear and simple.
- GitHub releases are created by hand by Mark. Cloud sessions can't create them.

## Site structure
- `index.html`: homepage. `css/style.css`: shared styles. `Mark_Herdt_CV.pdf`: resume.
- `games/watermelon-game.html`, `games/queue-connect.html`
- `games/rogue-deck/`: `index.html`, `liveops.html` (battle pass, LiveOps plan), `ab-test.html`
- `tools/economy-sim/` and `tools/ab-test/`: Python scripts and READMEs behind the Rogue Deck pages.
- Homepage order in Games and Design Case Studies: Watermelon Game (released), Rogue Deck, Queue-Connect.
- Skills card "LiveOps & Economy": LiveOps planning, Economy simulation, Experiment design, Retention metrics, Balancing spreadsheets.

## Project facts
- Rogue Deck is Mark's in-development multiplayer card roguelike. Balancing data lives in the "Rogue Deck Balancing" Google Sheet.
- The A/B test data is simulated. The page notes that the Common-share metric can rise if players buy fewer higher rarities; a live test would use Common purchases per Common offer shown. Mark chose not to rework the metric.
- The A/B page's bootstrap check is a second 95% confidence interval from resampling whole players 1,000 times. It is a sanity check, not a decision rule.
- Battle pass leaderboard and milestone achievements count only earned XP, not paid level skips.

## Releases
Tags are `<tool>-v<major>.<minor>`, e.g. `ab-test-v1.0` ("Rogue Deck A/B Test Analysis", asset `rogue-deck-ab-test.zip`). Release notes say when data is simulated.

## Interview caveats
- Retention metrics are planned, not measured in a live game.
- The economy simulation was written with AI help.
