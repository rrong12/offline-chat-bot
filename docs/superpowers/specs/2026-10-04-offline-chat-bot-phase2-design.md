# Offline Chat Bot: Phase 2 Design (Trivia, Riddle, Higher or Lower)

Date: 2026-10-04
Status: approved by Robert on 2026-10-05 (from a high-level summary). The decisions come from the design conversation on 2026-10-04.
Builds on: `2026-10-04-offline-chat-bot-design.md` (Phase 1: personal games, GameManager, stats).

## 1. Scope

Three new **personal** games, each a `Game` class plugged into the Phase 1 `GameManager`:

| Command | Game |
|---|---|
| `?trivia [category] [difficulty]`, `?trivia categories` | Trivia |
| `?riddle` | Riddle |
| `?higherlower` (alias `?hl`) | Higher or Lower streak |

Family Feud was dropped (Robert, 2026-10-04), so Phase 2 needs no chat-wide game mode.

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Mode | Personal, like Scramble and Hangman | Robert's choice. |
| How to answer | `?g <answer>` in all three games; plain chat is ignored | Same as Hangman. A stray "hmm" never burns one of your guesses. |
| Trivia source | Open Trivia DB, verified questions only, downloaded once into a bundled file | Its API allows one request per 5 s per IP, too slow for live use with 25 games. CC BY-SA 4.0, so it needs credit. |
| Trivia categories | general, games, movies, music, tv, anime, sports, science, geography, history, animals | Robert picked the curated 11. |
| Trivia format | Easy: multiple choice. Medium and hard: typed answers | Robert's choice. |
| Riddle guesses | 3 per riddle | Robert's choice. |
| Riddle hints | 1st: a written clue toward the idea. 2nd: letter count and first letter | Robert asked for hints that actually help. |
| Riddle content | About 150 riddles with clues, written and checked by AI agents at build time and enforced by tests. Robert's review is optional | Robert's choice. |
| Higher or Lower data | Monthly English Wikipedia page views (Wikimedia API), downloaded into a bundled file and refreshable by a script | Robert chose (a). Real Google search volumes need paid tools. |
| Higher or Lower scoring | 1 point per correct guess | Recommended, and Robert didn't object. |

## 3. Trivia

### Question bank (`bot/content/trivia.json`)
- **How it's built:** by `scripts/fetch_trivia.py`, run once. It pulls **verified** questions per category using an Open Trivia DB session token, at most one request every 5 seconds, then decodes HTML entities.
- **Category mapping** (Open Trivia DB IDs):

  | Our category | Open Trivia DB categories |
  |---|---|
  | general | General Knowledge 9 |
  | games | Video Games 15 |
  | movies | Film 11 |
  | music | Music 12 |
  | tv | Television 14 |
  | anime | Japanese Anime & Manga 31 |
  | sports | Sports 21 |
  | science | Science & Nature 17, Computers 18, Mathematics 19 |
  | geography | Geography 22 |
  | history | History 23 |
  | animals | Animals 27 |

- **Easy:** only `type=multiple` questions. True/false questions are excluded, since guessing wins half the time.
- **Medium and hard, typed:** kept only if typeable:
  - the answer is at most 3 words and 25 characters;
  - the question doesn't contain "which of these", "which of the following", "all of the above", "none of" or a capitalised NOT;
  - questions with purely numeric answers are kept, but must be answered exactly.
- **Blocked words:** questions whose text, answer, or options contain a blocked word (Phase 1's `BlockedWords` check over `content/blocked_rot13.txt`) are dropped, and a content test enforces it.
- **Credit:** `bot/content/TRIVIA_CREDITS.md` credits Open Trivia DB (CC BY-SA 4.0), and the README mentions it.

### Play
- **Easy:**
  - Shows `❓ (science, easy) What gas do plants absorb? A) Oxygen B) Carbon dioxide C) Nitrogen D) Helium · 20s · answer with ?g A-D`.
  - The options are shuffled once. You get one guess, either a letter or the option text.
  - Right: 5 points. Wrong: "❌ It was B) Carbon dioxide."
- **Medium and hard:**
  - Shows the question, `30s · ?g <answer> · ?hint`.
  - **Guesses:** 3. A wrong guess replies "❌ Not it, 2 guesses left."
  - **Matching:** the normalized guess equals an accepted answer. Answers of 5 or more letters allow one typo (Damerau-Levenshtein distance 1); numbers must be exact.
  - **Hints** (at most 2): first "7 letters, starts with J", then about half the letters revealed in place, as in Scramble's second hint.
  - **Points:** medium 10, 7 or 4; hard 15, 10 or 6, depending on hints used.
- **Starting:**
  - The difficulty is picked at random if not given.
  - An unknown category or difficulty lists the options without echoing what was typed.
  - The same question isn't repeated to the same player within their last 50 questions.

## 4. Riddle

### Content (`bot/content/riddles.json`)
- **Each entry:** riddle text, accepted answers (the main one first), and a clue.
- **About 150 classic, clean riddles.** One agent writes them and a second, independent agent checks them: the answer is right, the clue helps without giving it away, and the content is appropriate.
- **Content tests enforce:**
  - every riddle has a clue;
  - the clue contains no accepted answer, and no word sharing a 4-letter-or-longer stem with one;
  - no duplicate riddles;
  - riddle text is at most 300 characters;
  - no riddle, answer, or clue contains a blocked word.

### Play
- **Start:** `🧩 What has hands but can't clap? · 60s · ?g <answer> · ?hint`.
- **Guesses:** 3. A guess wins if, after normalization and dropping a leading "a", "an" or "the", it contains an accepted answer as whole words ("is it a clock" counts). A wrong guess replies "❌ Not it, 2 guesses left." After 3 wrong guesses: "💀 It was: a clock."
- **Hints:** first `💡 Clue: You probably check me several times a day.`, then `💡 5 letters, starts with C`.
- **Points:** 10, 7 or 4 by hints used.

## 5. Higher or Lower

### Data (`bot/content/higherlower.json`)
- **About 400 well-known terms** across games, celebrities, streamers, foods, brands, animals, countries, movies and sports.
- **Each term has:** the display name, the Wikipedia article title, and its average daily views over the last full month, as monthly views.
- **Built by `scripts/fetch_pageviews.py`** through the Wikimedia REST API, with a generic User-Agent that includes the public repo URL as contact, and no personal email. Re-running it refreshes the numbers.
- **Content tests enforce:**
  - every term has a view count above 0;
  - no duplicates;
  - every name passes the same appropriateness rules as the word lists, including the blocked-word check.

### Play
- **Start:** `↕️ Minecraft gets 241K monthly Wikipedia views. Does Kai Cenat get higher or lower? · 20s · ?g higher / ?g lower`.
- **Answers:** `higher`, `lower`, `h` or `l`. Ties count as correct either way.
- **Correct:** reveal the number, streak +1, and the revealed term becomes the next comparison. The round timer restarts, so each guess gets 20 s.
- **Wrong or timeout:** `❌ Pizza: 55K. Game over, streak 4 (+4)`.
- **Pairs:** each pair differs by at least 15%, so it isn't a coin flip, and no term repeats within one game.
- **Numbers:** shown as 55K, 1.2M.

## 6. Framework changes (to Phase 1 code)

- **`Outcome.restart_timer: bool = False`.** When set on an outcome that doesn't finish the game, GameManager resets `session.start_mono`. Higher or Lower uses it. This was deferred to Phase 2 by the Task 8 review.
- **Shared in-game commands get generic help text,** since several games now declare `?g` and `?hint`: "Guess in your current game" and "Get a hint in your current game". Each game's own `?help <game>` text still explains its rules.
- **Scramble also accepts `?g <word>`,** in addition to plain chat, so `?g` works in every game.
- **Aliases:** `?hl` for `?higherlower`. Start handlers are already bound per game class (Task 10).

## 7. Testing

- **Pure game tests:** each game with a seeded RNG and tiny fixture content, covering every win, loss, hint and timeout path, typo tolerance, the guess limits, and timer restarts.
- **Content tests:** for `trivia.json`, `riddles.json` and `higherlower.json`, using the rules above.
- **Flow tests through the console connector:** one full game of each.
- **Live:** added to the Phase 1 live checklist the next time it's run.

## 8. Changes made while building (2026-10-05)

Reviews of the built games led to these refinements; the plan's execution log has the details.

- **No repeats:** remembered in memory since the bot started. When a small pool is used up, the
  question seen longest ago comes back, never the one just played.
- **Trivia question bank:** about 2,830 questions after removing mature topics (drugs, alcohol,
  tobacco, sexual themes, self-harm), real tragedies, graphic horror, questions that need their options shown, typed answers that
  can't be typed fairly (symbols like C++, decimals, dates, long numbers), duplicates, and questions
  checked and found wrong or out of date. `?help trivia` names Open Trivia DB and the license.
- **Trivia matching:** typo tolerance only inside a word of 5+ letters and never on the first letter;
  numbers, one-letter words and Roman numerals must be exact. Natural variants count: "Cupertino" for
  "Cupertino, California", "88" for "88 mph", "3" for "Three", "WW2" for "World War II", the surname
  for questions about a person, a name without its title or middle initial, initials ("CPU"), words the
  question already says left out, and a pair in either order.
- **Riddle matching:** a guess wins if it names an accepted answer; filler words ("I think it's a")
  and words from the riddle don't make it a list, but naming other answers, "either or", a negation
  ("not a clock"), a different number, or another letter (for the letter riddles) doesn't win.
- **Higher or Lower:** a streak of 5 or more counts as a win in `?gamestats`; display names say
  what's meant when ambiguous ("Venom (the movie)").
- **Starting games:** a game without options ignores extra words (`?hl lets go`); `?leaderboard hl`
  works.

## 9. Out of scope

Chat-wide games, Family Feud, live API calls during play, and `?rng`, `?ascii`, `?chatsummary` (Phases 3 and 4).
