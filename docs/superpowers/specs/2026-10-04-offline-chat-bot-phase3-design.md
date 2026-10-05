# Offline Chat Bot: Phase 3 Design (?rng)

Date: 2026-10-04
Status: approved by Robert on 2026-10-05 (from a high-level summary). The decisions come from the design conversation on 2026-10-04.

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

| Tier | Points | Badges (numbers out of 1,000,001 that earn it) |
|---|---|---|
| Legendary | 100 | Zero (1); Max (1); Six of a kind, 111111 ... 999999 (9); Straight, 123456, 654321, 012345 and similar (10); Round hundred-thousand, 100000 ... 900000 (9); Nice nice nice, 696969 (1)*; Blaze it, 420420 (1)* |
| Rare | 40 | Power of two (20); Fibonacci (29); Round ten-thousand (90); Perfect cube (100); Five in a row (180); 1337 (300); Palindrome, 6 digits (1,000); Perfect square (1,000) |
| Uncommon | 15 | Four in a row (2,610); Contains 420 (3,999)*; Ends in 00 (9,900); All even digits (15,625); All odd digits (15,625); Five-digit palindrome, the first or last five digits (19,890) |
| Common | 5 | Triple, three identical in a row (34,110); Doubles, two different repeated pairs (47,160); Lucky sum, digit sum 7, 13 or 21 (48,686); Contains 69 (49,401)*; Contains 67 (49,401); Prime (78,498) |

**Updated while building (2026-10-05):** the tiers follow each badge's measured count, so a few badges
moved from this table's first draft (Round hundred-thousand up to legendary; Round ten-thousand,
Palindrome and Perfect square to rare; Ends in 00 to uncommon; Contains 69 and 67 to common). 27
badges. Numbers are checked and shown as six digits with leading zeros ("rolled 001,337"), so the
zeros that earn a badge are visible. About 68% of rolls earn no badge; a roll averages about 2.7
points.

Badges marked * are the meme badges. `[rng] meme_badges = true` in `config.toml` turns them on (the default; Robert chose to include them), and `false` turns them off without a code change.

The exact rules and each badge's count are unit-tested over all 1,000,001 numbers.

## 3. Data

- **Migration 2:** table `rng_rolls(user_id, utc_date, number, score, badges_json, rolled_at, PRIMARY KEY (user_id, utc_date))`. `rolled_at` breaks ties in the top lists (whoever rolled first).
- **Once per day:** enforced by the primary key, with the same atomic pattern as `?cookie`.
- **Points:** `?rng today` and `?rng top` read from `rng_rolls`, and the leaderboard points come from the matching round row.

## 4. Testing

- Every badge rule, at its boundaries.
- A badge-frequency simulation over all 1,000,001 numbers, confirming each tier's rarity.
- The once-per-day rule across the UTC boundary.
- `meme_badges = false`.
- Leaderboard integration.
- Flow tests for every subcommand.
