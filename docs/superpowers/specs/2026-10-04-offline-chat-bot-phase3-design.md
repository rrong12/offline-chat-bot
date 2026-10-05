# Offline Chat Bot: Phase 3 Design (?rng)

Date: 2026-10-04
Status: draft for Robert's review. The decisions come from the design conversation on 2026-10-04.

## 1. Behaviour

| Command | Effect |
|---|---|
| `?rng` | Your one roll for the UTC day: a uniform random number from 0 to 1,000,000, scored by badges. If you've already rolled today, it repeats today's roll and when the next one comes. |
| `?rng me` | Your roll today, plus your best roll ever. |
| `?rng <user>` | The same for someone else. A name that isn't found is never echoed. |
| `?rng today` | Today's top 5 rolls by score. |
| `?rng top` | The top 5 single rolls of all time. |

Example: `🎲 alice rolled 123,321 · 🏅 Palindrome (rare, 40) · 🏅 Triple digit (common, 5) · 45 pts`.

**Leaderboard:** rng points count on the main `?leaderboard` and in `?gamestats` (Robert, 2026-10-04). Each roll is recorded as a one-player round of the game "rng", with the score as its points.

## 2. Badges

About 30 badges in 4 tiers. A roll earns every badge it matches, and the score is the sum.

| Tier | Points | Badges |
|---|---|---|
| Legendary | 100 | Zero (0); Max (1,000,000); Six of a kind (111111 ... 999999); Straight (123456, 654321, 012345 and similar); Nice nice nice (696969)*; Blaze it (420420)* |
| Rare | 40 | Palindrome (6 digits); Five in a row (five identical digits); Round hundred-thousand (100000 ... 900000); Fibonacci number; Power of two; Perfect cube; 1337 |
| Uncommon | 15 | Palindrome (5 digits); Four in a row; Round ten-thousand; Perfect square; All even digits; All odd digits; Contains 69*; Contains 420*; Contains 67 |
| Common | 5 | Prime; Triple digit (three identical in a row); Ends in 00; Digit sum 7, 13 or 21 (lucky sum); Doubles (contains at least two different repeated pairs) |

Badges marked * are the meme badges. `[rng] meme_badges = true` in `config.toml` turns them on (the default; Robert chose to include them), and `false` turns them off without a code change.

The exact rules (leading zeros, 6-digit formatting) and the probability of each badge are defined and unit-tested in the plan, so the tiers match the real rarity.

## 3. Data

- **Migration 2:** table `rng_rolls(user_id, utc_date, number, score, badges_json, PRIMARY KEY (user_id, utc_date))`.
- **Once per day:** enforced by the primary key, with the same atomic pattern as `?cookie`.
- **Points:** `?rng today` and `?rng top` read from `rng_rolls`, and the leaderboard points come from the matching round row.

## 4. Testing

- Every badge rule, at its boundaries.
- A badge-frequency simulation over all 1,000,001 numbers, confirming each tier's rarity.
- The once-per-day rule across the UTC boundary.
- `meme_badges = false`.
- Leaderboard integration.
- Flow tests for every subcommand.
