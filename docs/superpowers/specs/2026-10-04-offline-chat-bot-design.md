# Offline Chat Bot: Design (Phase 1)

Date: 2026-10-04
Status: approved by Robert 2026-10-04; revised the same day for personal (single-player) games

## 1. Goal

A custom Twitch chat bot for jasontheween's offline chat. It runs chat games and quick fun
commands, tracks points per game with leaderboards and stats, can be paused or shut down from
chat by moderators, and keeps an activity log.

The feature list comes from the requester's reference screenshots (18 `?` commands). That
list is too large for one build, so it is split into four phases. **This spec covers Phase 1
in full** and records the requirements for Phases 2 to 4 so the Phase 1 design accommodates
them. Each later phase gets its own short spec.

| Phase | Contents |
|---|---|
| **1 (this spec)** | Core (Twitch connection, admin controls, activity log, outbox, stats database, game manager), `?help` / `?commands`, `?leaderboard`, `?gamestats`, `?scramble` (+ `?hint`), `?hangman` (+ `?g`), `?skip`, `?8ball`, `?coinflip`, `?catfact`, `?dogfact`, `?fact`, `?dadjoke`, `?cookie` |
| 2 | `?trivia` (+ `?hint`), `?riddle`, `?higherlower` (Family Feud was dropped, 2026-10-04) |
| 3 | `?rng` (own badge rules) |
| 4 | `?ascii`, `?chatsummary` / `?cs continue` |

Not built: the `casino` option of `?leaderboard`. The bot has no gambling or currency.

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Language and library | Python 3.12, TwitchIO 3.3.x | TwitchIO handles OAuth, token refresh, EventSub WebSocket reconnects, and the Helix API. Python 3.11 to 3.13 are supported; the local machine has 3.12. |
| Reading chat | EventSub WebSocket, `channel.chat.message` | Twitch's recommended path. IRC still works but is the legacy interface. |
| Sending chat | Helix Send Chat Message with the **app access token** | With the bot modded, this shows Twitch's Chat Bot badge. A user token would not. |
| Channel access | The bot account is **modded** in the channel | Raises the send limit to 100 per 30 s, bypasses slow mode and followers-only, and needs no authorization from Jason. A contact of Robert's will mod it after a demo. |
| Command prefix | `?`, configurable | Matches the requested command list. No other `?` bot is known to be in the chat. |
| Who can play | Every user | Requested. |
| Who can control the bot | Broadcaster, any moderator, and listed owners (Robert); all control commands | Option (b), plus the owner so Robert can control his bot in a chat where he is not a mod. |
| Shutdown | `?bot shutdown` exits the process for real (emergency kill switch) | No chat command can restart a stopped process. `?bot off/on` covers everyday pausing. |
| Auto-pause when live | No | The bot runs whether or not Jason is live. Mods use `?bot off` if needed. |
| Points | Per game, stored per round, plus leaderboard and stats | Requested (`?gamestats`, `?leaderboard [game]`). |
| Logs | Bot activity only, JSONL, one file per UTC day, 30-day retention | No full chat archive. |
| Where it runs | Robert's laptop for development and testing in his own channel. Later, an always-on Linux server under systemd | Moving to the server is a copy plus a service file. |
| Shared chat | Only messages from the bot's own channel count | Partner channels' mods cannot control the bot, and games are not flooded. |
| Game mode | **Personal**: `?scramble` starts your own game, only your answers count, and replies are threaded to you. Every planned game is personal. | People play whenever they want instead of waiting for one shared game. Chosen by Robert. |
| Private replies | Not possible at scale; threaded replies instead | Twitch caps bot whispers at 40 unique recipients per day, many users block whispers from strangers, and whispers can be dropped silently. Using extra accounts to get around the cap violates Twitch's developer agreement. |
| Game limits | One game per person; up to 25 running at once; a 10 s per-person cooldown after a game; new games are refused while 10+ bot messages are waiting to send (busy brake) | Keeps the bot from flooding a busy chat while letting many people play. All adjustable in `config.toml`. |
| Send rate | 2 messages/s sustained, burst 3; 0.6/s with burst 1 when the bot is not a mod | About 60% of Twitch's mod limit (100 per 30 s), and under the non-mod limit (20 per 30 s). |
| Hangman guessing | Explicit `?g <letter>` or `?g <answer>`; plain chat is ignored | "W" and "L" are constant reactions in Jason's chat and would otherwise count as guesses. |
| Scramble hints | On request with `?hint` (10, 7, or 4 points), never automatic | Keeps each personal game to a few messages. |
| Word categories | `animals`, `countries`, `food`, `games`, `general`, `streamers` | Chosen by Robert from a pitch. Emotes, slang, Twitch terms, and memes were declined. |

## 3. Twitch integration

### Accounts and app
- **Bot account:** a dedicated Twitch account with a verified email.
- **Twitch app:** registered at dev.twitch.tv/console. Category "Chat Bot", client type
  Confidential (a client secret is needed for the app access token), OAuth redirect
  `http://localhost:4343/oauth/callback`.
- **Bot account scopes**, granted once through `python -m bot auth`:
  - `user:read:chat`: read chat through EventSub.
  - `user:write:chat` and `user:bot`: send through Helix with the app token.
  - `user:read:moderated_channels`: lets the startup check confirm the bot is a mod.
- **Tokens:** TwitchIO stores and refreshes tokens in `data/.tio.tokens.json`, which is
  Git-ignored.

### Startup sequence
1. Load `.env` and `config.toml`.
2. Log in: the app token comes from the client credentials, and the bot user token is loaded
   from the token file.
3. Resolve the configured channel login to a broadcaster ID (Helix Get Users).
4. Check the bot's moderated channels. If the channel is missing, log a warning ("not a mod:
   no Chat Bot badge, slow mode applies, sending slowed to 0.6/s"), send with the bot's own
   user token (Twitch refuses app-token sends from a non-mod), and continue. This lets the bot
   run in a test channel before it is modded. If mod status is removed while running, the
   first refused send (HTTP 403) switches to the same non-mod mode and logs `LostModStatus`.
5. Subscribe over WebSocket to `ChatMessageSubscription(broadcaster_user_id=<channel>,
   user_id=<bot>)` using the bot token. This must happen within 10 s of the socket's welcome
   message; TwitchIO handles the timing.
6. Post nothing on startup, and log `startup`.

### Limits the bot must respect
- Messages are capped at 500 characters, so the outbox truncates at a word boundary.
- The send rate is 100 per 30 s as a mod (20 per 30 s and 1/s otherwise). The outbox sends at
  2/s (section 9).
- Each WebSocket connection has a 10-subscription-cost budget. Phase 1 uses one subscription.
- With the app token, messages during a shared chat go only to the source channel. That is
  the Twitch default since 2025-05-19 and is what we want.

### Incoming message filtering, in order
1. Drop the bot's own messages (chatter ID equals the bot ID).
2. Drop shared-chat messages from other channels (`source_broadcaster` set and not equal to
   the channel).
3. If paused, drop everything except `?bot ...` from a controller.
4. Route the message to a command, or to the active game.

## 4. Architecture

```
offline-chat-bot/
├── pyproject.toml
├── config.toml              non-secret settings (channel, prefix, cooldowns, game settings)
├── .env                     secrets (Git-ignored)
├── bot/
│   ├── __main__.py          CLI: `python -m bot` (run), `python -m bot auth`, `python -m bot console`
│   ├── config.py            loads and validates .env and config.toml into a Config object
│   ├── core.py              BotCore: filtering, routing, pause state; connector-agnostic
│   ├── connectors/
│   │   ├── base.py          ChatMessage dataclass + Connector protocol
│   │   ├── twitch.py        TwitchIO implementation (EventSub in, Helix out)
│   │   └── console.py       stdin/stdout implementation for local play and tests
│   ├── commands.py          command registry: name → handler, aliases, permission, cooldowns,
│   │                        usage + description (the single source for ?help)
│   ├── permissions.py       is_controller(msg): broadcaster or moderator or owner
│   ├── cooldowns.py         per-user and global cooldown tracking (injectable clock)
│   ├── admin.py             ?bot off/on/status/shutdown, ?stopgame
│   ├── stats.py             StatsStore (SQLite): rounds, players, users, daily uses, bot state
│   ├── stats_commands.py    ?leaderboard, ?gamestats
│   ├── fun.py               ?8ball, ?coinflip, ?catfact, ?dogfact, ?fact, ?dadjoke, ?cookie
│   ├── http.py              shared aiohttp session, 3 s timeout, fallback helper
│   ├── outbox.py            rate-limited, bounded, coalescing send queue
│   ├── activity_log.py      JSONL activity log, daily files, retention
│   ├── text.py              answer normalization, truncation, username validation
│   ├── assets.py            loads bundled files from content/ (word lists, fortunes, fallbacks)
│   ├── games/
│   │   ├── base.py          Game interface, Outcome
│   │   ├── manager.py       GameManager: personal sessions, limits, timers, cooldowns, scoring
│   │   ├── scramble.py
│   │   └── hangman.py
│   └── content/             bundled data: word lists per category, fortunes, 8ball answers,
│                            fallback facts and jokes (plain text, one item per line)
├── data/                    runtime state (Git-ignored): bot.db, .tio.tokens.json, logs/
└── tests/
```

### The connector boundary
`BotCore` never imports TwitchIO. A connector delivers `ChatMessage` objects and sends text:

```python
@dataclass(frozen=True)
class ChatMessage:
    id: str
    user_id: str
    login: str             # lowercase username
    display_name: str
    text: str
    is_broadcaster: bool
    is_moderator: bool
    source_channel_id: str | None   # set during shared chat
    received_at: datetime  # UTC

class Connector(Protocol):
    # on_ready(ReadyInfo(channel_login, channel_id, is_mod)) runs once connected, and again
    # if mod status is lost while running.
    async def run(self, on_message: OnMessage, on_ready: OnReady) -> None: ...
    async def send(self, text: str, reply_to: str | None = None) -> SendResult: ...
    async def lookup_user(self, login: str) -> UserRef | None: ...   # Helix Get Users
    async def close(self) -> None: ...
```

- **TwitchConnector** maps TwitchIO's `ChatMessage` (with `chatter.broadcaster` and
  `chatter.moderator`) to this dataclass. It uses TwitchIO's `Client` directly, not the
  `commands` extension, so command routing is our own and works the same in console mode.
- **ConsoleConnector** reads lines like `alice: ?scramble` or `@mod_bob: ?bot off`, where a
  leading `@` marks a moderator. It prints the bot's output. `lookup_user` accepts any valid
  username.

### Message flow
`Connector → BotCore.on_message → filter → command registry (if prefixed) or
GameManager.on_message (if the sender has a game running) → handlers produce text → Outbox →
Connector.send`.

A single 1-second tick loop calls `GameManager.tick(now)` and the log-retention check. Games
never create their own timers, so tests can drive time directly.

## 5. Commands (Phase 1)

Cooldowns, unless noted: each command has a **10 s per-user** cooldown and a **5 s global**
cooldown. A command on cooldown is silently ignored.
- Personal lookups (`?cookie`, `?gamestats`, `?help`) have only the per-user cooldown, so one
  person's use never blocks another's.
- While the busy brake is on (section 6), Stats, Fun, and Info commands are ignored, so game
  messages keep flowing. Control and in-game commands still work.
- Game start commands (`?scramble`, `?hangman`) have no command cooldowns. The per-player game
  cooldown (10 s after your game ends) is the only limit on starting, and the game manager
  rate-limits its "can't start" and category-list replies to one per 5 s per player and game.
- Control commands (`?bot ...`, `?stopgame`), `?skip`, and in-game commands such as `?g` and
  `?hint` have no cooldowns; each game enforces its own limits on its in-game commands. Quick-command answers use Twitch's
threaded reply (`reply_to`). Game messages are threaded under the player's latest message.

| Command | Who | Behavior |
|---|---|---|
| `?bot off` | controller | Pause. Ends all running games (outcome `stopped`, no points), persists `paused=1`, replies "Bot paused by \<name\>. `?bot on` to resume." |
| `?bot on` | controller | Resume and persist `paused=0`. |
| `?bot status` | controller | "ON/PAUSED · up 3h12m · games: 4 running · v0.1.0". Works while paused. |
| `?bot shutdown` | controller | Sends "Shutting down (requested by \<name\>)." at priority, ends all games, logs `admin`/`shutdown` with the user, flushes the outbox (max 3 s), closes the connector, exits with code 0. |
| `?stopgame` | controller | Ends all running games. Outcome `stopped`, no points (Phase 2: a Higher or Lower streak keeps its points). Replies "🛑 Stopped N games. Only streak points already earned are kept." |
| `?skip` | anyone with a game running | Ends your own game: "⏭️ Skipped. It was ALLIGATOR." Outcome `skipped`, no points. |
| `?help` / `?commands` | anyone | One message listing the public commands, grouped (Games, Stats, Fun), ending with "?help <command> for details". Built from the registry, so it never drifts. Control commands are left out to keep it short. |
| `?help <command>` | anyone | The usage line and description for one command, with or without the `?`. Works for control commands too (`?help bot`). Unknown command: "No command named \<x\>. Try ?help." |
| `?leaderboard [game] [limit]` | anyone | Top N (default 5, clamped 1 to 10) by points for one game, or across all games when no game is named. "Top 5 scramble: 1. a (120) 2. b (98) …". Ties go to more wins, then login. A numeric argument is the limit. |
| `?gamestats [game] [username]` | anyone | With no game: totals plus a per-game breakdown (wins, played, points), truncated to fit. With a game: wins, played, points, and rank in that game. If the first argument matches a game name it is the game; otherwise it is a username. A leading `@` is stripped. Unknown user: "No stats for \<name\> yet." Defaults to the caller. |
| `?scramble [category]` | anyone | Start your own Scramble (section 7). With no category, one is picked at random and named in the opening message. |
| `?hint` | anyone with a Scramble running | Next hint for your word (at most two; each lowers the points). |
| `?scramble categories` | anyone | "Scramble categories: animals, countries, …". Starts nothing and works while a game is running. |
| `?hangman [category]` | anyone | Start your own Hangman (section 7). Same random pick as Scramble when no category is given. |
| `?hangman categories` | anyone | Same as `?scramble categories`, for Hangman. |
| `?g <letter>` / `?g <answer>` | anyone with a Hangman running | Guess a letter or the whole answer in your game (section 7). Ignored otherwise. |
| `?8ball [question]` | anyone | One of 20 classic answers from `content/8ball.txt`. The question is not echoed. |
| `?coinflip` | anyone | "Heads" or "Tails". |
| `?catfact` | anyone | `GET https://catfact.ninja/fact` → `fact`. |
| `?dogfact` | anyone | `GET https://dogapi.dog/api/v2/facts` → `data[0].attributes.body`. |
| `?fact` | anyone | `GET https://uselessfacts.jsph.pl/api/v2/facts/random?language=en` → `text`. |
| `?dadjoke` | anyone | `GET https://icanhazdadjoke.com/` with `Accept: application/json` and a descriptive `User-Agent` → `joke`. |
| `?cookie` | anyone | Once per UTC day: a random fortune from `content/fortunes.txt`. If already used: "You already opened today's cookie. Next one in 3h 12m (00:00 UTC)." |
| `?cookie give <username>` | anyone | Uses the giver's daily cookie on someone else: "@a gave @b a fortune cookie: …". The username must match `^[A-Za-z0-9_]{3,25}$` and exist (`lookup_user`). Giving to yourself is not allowed. Counts as the giver's cookie for the day; the recipient's own cookie is unaffected. |

**Facts and jokes:** all four APIs were verified working on 2026-10-04. Each call has a
3-second timeout. On failure, the bot uses a random line from the matching
`content/fallback_*.txt` list (about 50 entries each). API text is cleaned and checked first,
since the modded bot's messages skip Twitch's chat filters:
- it must be a string; it is NFC-normalized, invisible and control characters are removed, and
  whitespace is collapsed;
- it is rejected (fallback used) if it is empty or over 400 characters, contains a link (`://`
  or `www.`) or an `@mention`, starts with a lowercase letter (it looks cut off), or contains a
  blocked word. Text is never truncated.
- Blocked words come from `content/blocked_prose_rot13.txt` (ROT13-encoded), separate from
  Scramble's fragment list. Each pattern says how it matches: `word` is the whole word or its
  plural, `word*` any word starting with it, and `*word*` any word containing it (for swears
  that appear inside compounds). A short list of innocent look-alikes (analysis, Dickinson,
  Milford, Scunthorpe, ...) is exempt, as are "Homo sapiens" and "Maine Coon" (also when
  misspelled "Main Coon"). Of about 1,360 real API texts checked on 2026-10-04, only one is
  rejected for a blocked word: a fact naming Hitler, as intended.

Starting a game when you already have one gets "You already have a \<game\> game running."
During your cooldown it gets "Your next game in \<n\>s." At the limit (25 games) or while the
busy brake is on, it gets "Too many games running right now, try again in a moment." These
replies, the category list, and "Couldn't start that game." are limited to one per 5 s per
player and game.

## 6. Game framework

### Interface (`games/base.py`)

```python
@dataclass
class Outcome:
    messages: list[str] = field(default_factory=list)
    awards: dict[str, int] = field(default_factory=dict)   # user_id → points
    winners: set[str] = field(default_factory=set)          # user_ids counted as winners
    finished: bool = False
    result: Literal["won", "timeout", "lost"] | None = None # set when finished
    coalesce_key: str | None = None                         # e.g. "hangman-board"

class Game(ABC):
    name: ClassVar[str]              # "scramble"; also the start command
    categories: ClassVar[list[str]]  # [] if the game has no categories
    time_limit: ClassVar[int]        # seconds
    commands: ClassVar[tuple[str, ...]] = ()   # in-game commands, e.g. ("g",) for Hangman

    def __init__(self, category: str | None, rng: random.Random, assets: Assets): ...
    def start(self) -> str: ...
    def on_message(self, msg: ChatMessage, now: datetime) -> Outcome | None: ...
    def on_command(self, name: str, args: str, msg: ChatMessage, now: datetime) -> Outcome | None: ...
    def on_tick(self, elapsed: float) -> Outcome | None: ...   # default: None
    def on_timeout(self) -> Outcome: ...
    def reveal(self) -> str: ...                               # answer text for skip/stop
```

Games are pure. They take messages and time as input, return outcomes, and do no I/O.
Randomness comes from an injected `random.Random`, so tests can seed it.

### GameManager rules (personal games)
- **Sessions:** each player has at most one running game, keyed by user ID. Many players can
  play at once.
- **Start:** `?<name> [category]` starts the sender's game unless they already have one, their
  cooldown (`games.cooldown_seconds`, default 10 s) is running, `games.max_running` (default 25)
  games are running, or the busy brake is on (`games.busy_queue`, default 10 queued bot messages).
  - With no category, one is chosen at random, and the opening message names it.
  - An unknown category gets the category list and starts nothing.
- **Category list:** `?<name> categories` replies with the game's categories and starts
  nothing. It works any time, subject to the 5 s reply limit. `categories` is reserved and
  cannot be a category name.
- **Routing:** a player's plain chat goes to their own game only; everyone else's chat is
  ignored by it. In-game commands (`?g`, `?hint`) go to the sender's game if it declares them,
  and are ignored otherwise.
- **Replies:** every game message is a threaded reply to the player's latest message (the start
  command, or the answer or command that produced it). Board updates coalesce per player.
- **Timers:** the 1 s tick checks every running game; at `time_limit` it calls `on_timeout()`.
- **Finishing:** when an `Outcome` has `finished=True`, the manager records the round with the
  player's points, logs `game_end`, replies with the messages, and starts that player's cooldown.
- **Skip and stop:** `?skip` ends the sender's game (`skipped`, no points, the answer is
  revealed). `?stopgame`, `?bot off`, and shutdown end every game (`stopped`, no points).
- **Errors:** an exception from game code is logged with a traceback. That player's game is
  recorded as `stopped` with no points, and they get "Game ended due to an error." Other games
  and the bot keep running.
- **Help text:** each game supplies a `usage` and `description`, including its in-game commands,
  which `?help <game>` shows.
- **Registration:** games are listed in `config.toml` under `[games] enabled = [...]`. Adding
  a game takes one module plus one config entry.
- **Chat-wide games:** none are planned (Family Feud was dropped), so there is no chat-wide
  mode.

### Answer normalization (`text.normalize`)
1. Unicode NFKC.
2. Lowercase.
3. Remove format characters (category Cf), combining marks (Mn, Me), and the tag block
   U+E0000-E007F (Chatterino and 7TV append U+E0000 to repeated messages).
4. Replace punctuation with spaces.
5. Collapse whitespace and trim.

An answer matches only when the whole normalized message equals the normalized answer.
Substrings do not count, which avoids false positives in a busy chat.

## 7. Phase 1 games

### Scramble
- **Answer:** a random word from `content/words/<category>.txt`, 4 to 10 letters, letters
  only. The displayed scramble must differ from the word; reshuffle until it does.
- **Messages:**
  - start: "🔤 Unscramble (animals): LGRATIOAL · 60s · ?hint for a hint".
  - `?hint` (first use) shows the first and last letters (`A _ _ _ _ _ _ _ R`).
  - `?hint` (second use) reveals about half of the letters, chosen at random but stable.
    Further `?hint`s are ignored.
- **Answering:** the player types the word. Wrong answers cost nothing.
- **Win:** the player's message equals the word after normalization. Points are 10 with no
  hints, 7 after one, and 4 after two. "✅ \<name\> got it: ALLIGATOR (+7)".
- **Timeout:** at 60 s (45 s until Robert lengthened it after the live test, 2026-10-05), "⏰ Time's up! It was ALLIGATOR." No points.

### Hangman
- **Answer:** a random entry from `content/words/<category>.txt`. It may be a short phrase;
  spaces and punctuation are shown, and only letters are hidden.
- **Start:** "🪢 Hangman (animals): _ _ _ _ _ _ _ _ _ · guess with ?g <letter> or ?g <answer> · 6 lives, 120s".
- **Board:** `_ A _ _ M A N | wrong: E R T (3/6)`. Wrong letters are listed alphabetically,
  so guess order can't spell a word. Sent with `coalesce_key="hangman-board"`, so
  bursts of guesses produce one up-to-date board instead of a backlog.
- **Guessing:** only through the player's own `?g`. Plain chat messages are ignored, so "W"
  and "L" reactions never count.
  - `?g <letter>`, one letter A to Z, is a letter guess.
  - `?g <answer>`, anything longer, is a solve attempt.
  - At most one `?g` every 2 s.
  - Repeated letters are ignored.
  - A correct new letter earns its guesser 1 point, held until the round ends.
  - A wrong letter costs one of 6 lives.
- **Attempt:** any accepted `?g`.
- **Solve:** `?g <answer>` that equals the full answer, normalized, solves it. Wrong solve
  attempts cost nothing, so griefers cannot burn lives with junk words.
- **Win:** a full solve, or revealing the last hidden letter. The player gets 10 points plus
  their held letter points.
- **Loss:** after 6 wrong letters or 120 s, "💀 The word was …". No points, held letter points
  included.

### Categories at launch
| Category | Contents |
|---|---|
| `animals` | Common and well-known animals. |
| `countries` | Countries of the world (multi-word names like *SOUTH KOREA* go to Hangman). |
| `food` | Everyday food plus snack and fast-food items (TAKIS, RAMEN, BOBA, WINGSTOP, CHIPOTLE). |
| `games` | Popular and streamed video games (MINECRAFT, VALORANT, GEOGUESSR, BALATRO, *LETHAL COMPANY*). |
| `general` | Common, recognizable English words. |
| `streamers` | Well-known streamers, by the name chat uses (XQC, LUDWIG, POKIMANE, SHROUD, *KAI CENAT*). |

- **Size:** at least 100 entries per file, checked for appropriate content (no slurs, no
  sexual terms).
- **Scramble filter:** Scramble uses only single words of 4 to 10 letters from each file.
- **Hangman:** also uses multi-word phrases (shown in *italics*).
- **Adding a category:** add one text file to `content/words/`.
- **Review gate for `streamers` and `games`:**
  - Every entry must be a real, verifiable streamer or game. Each entry is checked against a
    public source while the list is built, and nothing is taken from memory alone.
  - Robert reviews both files and signs off before the bot goes live in any channel.

## 8. Data model (`data/bot.db`, SQLite, WAL mode)

```sql
CREATE TABLE users (
  user_id      TEXT PRIMARY KEY,
  login        TEXT NOT NULL,          -- lowercase; updated on each command use
  display_name TEXT NOT NULL,
  last_seen    TEXT NOT NULL           -- ISO UTC
);
CREATE INDEX users_login ON users(login);

CREATE TABLE rounds (
  round_id    INTEGER PRIMARY KEY,
  game        TEXT NOT NULL,
  category    TEXT,
  started_by  TEXT NOT NULL REFERENCES users(user_id),
  started_at  TEXT NOT NULL,
  ended_at    TEXT NOT NULL,
  outcome     TEXT NOT NULL CHECK (outcome IN ('won','timeout','lost','skipped','stopped'))
);

CREATE TABLE round_players (
  round_id INTEGER NOT NULL REFERENCES rounds(round_id),
  user_id  TEXT NOT NULL REFERENCES users(user_id),
  points   INTEGER NOT NULL DEFAULT 0,
  won      INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (round_id, user_id)
);

CREATE TABLE daily_uses (
  user_id  TEXT NOT NULL,
  feature  TEXT NOT NULL,              -- 'cookie' (Phase 1), 'rng' (Phase 3)
  utc_date TEXT NOT NULL,              -- YYYY-MM-DD
  result   TEXT,                       -- e.g. fortune text, JSON for richer results
  PRIMARY KEY (user_id, feature, utc_date)
);

CREATE TABLE bot_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- 'paused'
CREATE TABLE schema_version (version INTEGER NOT NULL);
```

- Rounds and players are written only when a round ends, in one transaction. A crash
  mid-round loses that round and nothing else.
- Leaderboards and stats are computed with queries over `round_players` joined to `rounds`.
  No running totals are stored, so nothing can drift.
- The daily limit uses an `INSERT` that fails on the primary key. That is atomic, so two
  quick `?cookie` messages cannot both succeed.
- Migrations are numbered SQL steps applied at startup, keyed off `schema_version`.
- Access uses the stdlib `sqlite3` module. Queries are small and fast, so blocking the event
  loop briefly is acceptable.

## 9. Outbox

- **Rate:** a token bucket with a sustained rate of 2 messages/s and a burst of 3. As a mod the
  bot could send about 3.3/s; the margin is intentional.
- **Send timeout:** each send gives up after 10 s, is logged, and is not retried.
- **Queue:** at most 30 messages. When it is full, new normal-priority messages are dropped
  and logged (`send_dropped`). Priority messages (admin replies, shutdown notice) go to the
  front.
- **Coalescing:** a message with a `coalesce_key` replaces any unsent queued message with the
  same key.
- **Truncation:** messages are cut at the last word boundary that fits 500 characters, with
  `…` appended.
- **Send results:** if Twitch returns `is_sent=false`, the `drop_reason` code and message are
  logged. No retries.
- **Shutdown:** the send loop finishes its current message, then the queue is flushed for at
  most 3 s in total. Anything left is logged as dropped.

## 10. Permissions

`is_controller(msg) = msg.is_broadcaster or msg.is_moderator or msg.user_id in OWNER_IDS`.

- Owners are listed by Twitch user ID in `.env`, because IDs survive renames.
- Moderator status comes from the badges on the message itself, so no extra API calls are
  needed.
- Shared-chat messages from other channels are dropped before this check (section 3).

## 11. Activity log

- **File:** `data/logs/activity-YYYY-MM-DD.jsonl`, one JSON object per line, with dates in UTC.
- **Fields:** each record has `ts` (ISO UTC) and `event`, plus fields specific to the event.
- **Events:**

| Event | Fields |
|---|---|
| `startup` | version, channel, is_mod |
| `connected` / `disconnected` / `reconnected` | — |
| `command` | user_id, login, command, args (truncated to 100 chars) |
| `admin` | user_id, login, action (`off`/`on`/`shutdown`/`stopgame`) |
| `game_start` | round, game, category, player |
| `game_end` | round, game, outcome, player, points |
| `send_dropped` | reason (queue full, or Twitch drop code) |
| `error` | where, exception type, message, traceback |
| `shutdown` | by (user or `signal`), exit code |

- Ordinary chat messages are never logged. Only commands and game events are.
- Files older than 30 days are deleted at startup and at each UTC day rollover.
- Human-readable logs also go to stderr through `logging`.

## 12. Configuration

`.env` (secrets, Git-ignored):
```
TWITCH_CLIENT_ID=...
TWITCH_CLIENT_SECRET=...
BOT_ID=...                 # printed by `python -m bot auth`
OWNER_IDS=12345,67890      # Robert's user ID; comma-separated
```

`config.toml`:
```toml
channel = "robert_channel"   # change to "jasontheween" to go live there
prefix = "?"

[cooldowns]
user_seconds = 10
global_seconds = 5

[games]
enabled = ["scramble", "hangman"]
max_running = 25
cooldown_seconds = 10
busy_queue = 10

[outbox]
rate_per_second = 2
burst = 3
max_queue = 30

[logs]
retention_days = 30
```

The config is validated at startup. An invalid value exits with code 2 and a message naming
the bad key. This includes a `busy_queue` larger than the outbox queue (the brake could never
engage) and, when connecting to Twitch, the placeholder `channel = "your_channel"`. Console mode
and `auth` accept the placeholder, so they work before the channel is set.

## 13. Error handling

| Failure | Behavior |
|---|---|
| WebSocket drop or reconnect | TwitchIO reconnects, honoring Twitch's reconnect message and the keepalive timeout. The bot logs `disconnected` and `reconnected`. Game timers keep running. Sending uses HTTP (Helix), not the socket, so a timeout message still goes out during the outage. |
| Token refresh fails or token revoked | Log "re-run `python -m bot auth`", exit with code 3. The server's service does not restart on code 3. |
| Channel not found | Exit code 2 with a message. |
| Bot not a mod | Warning, bot-token sends at 0.6/s (section 3). |
| Mod status removed while running | The refused send is retried with the bot token; sending slows to 0.6/s (section 3). |
| Exception in a command handler | Logged with a traceback. The user gets no reply. The bot continues. |
| Exception in game code | Section 6. |
| External API slow or failing | 3 s timeout, then the fallback list. |
| Twitch drops a sent message | Logged (section 9). |
| SIGINT or SIGTERM (Ctrl+C, systemd stop) | Same as shutdown without a chat message. Exit code 0. |
| Unhandled crash | Non-zero exit. On the server, systemd restarts it. |

Exit codes: `0` deliberate stop, `1` crash, `2` config or setup error, `3` authentication
needed.

## 14. Testing

1. **Unit tests** (pytest, pytest-asyncio):
   - normalization, truncation, and username validation;
   - cooldowns with a fake clock;
   - the outbox's rate, burst, queue limit, coalescing, and priority, with a fake clock;
   - permissions;
   - command parsing, including the `?gamestats` and `?leaderboard` argument disambiguation;
   - `?help` output stays under 500 characters, and every registered public command has usage
     and description text;
   - stats queries on a temporary database;
   - the daily-use UTC boundary;
   - Scramble and Hangman with a seeded RNG and explicit `now` and `elapsed` values;
   - GameManager: separate concurrent games, one per player, per-player cooldown, the running
     limit, the busy brake, hints, skip, stop-all, timeouts, and error-in-game.
2. **Full-flow tests** drive `BotCore` through a scripted `ConsoleConnector`. Scenarios:
   - Start scramble; another user's answer is ignored; a wrong answer, a right answer, points
     awarded, `?leaderboard` shows them.
   - Two players playing at once; `?hint` lowers the points.
   - Hangman win and loss through `?g`. Plain one-letter messages ("W") are ignored.
   - `?skip` ends your game; a timeout ends it; the busy brake refuses new games.
   - `?stopgame` ends everyone's games.
   - A non-mod's `?bot shutdown` is ignored. A mod's `?bot off` blocks games; `?bot on`
     restores them.
   - Paused state survives a restart.
   - Shared-chat messages are ignored.
   - `?cookie` twice on the same day, and again after UTC midnight.
   - A fact API timeout falls back to the bundled list.
3. **Live checklist in Robert's channel**, with the bot modded there, Robert's account, and a
   second non-mod account:
   - The startup log shows `is_mod=true`, and bot messages carry the Chat Bot badge.
   - Play both games to win, timeout, and skip, with two accounts playing at once, and check
     `?gamestats` and `?leaderboard`.
   - Try every quick command.
   - The non-mod's `?bot off` does nothing.
   - The mod's `?bot off`, `?bot status`, and `?bot on` work.
   - `?bot shutdown` stops the process with exit code 0.
   - Check the log file's contents.

## 15. Running

**Laptop (development):**
```
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp .env.example .env            # fill in client id and secret
.venv/bin/python -m bot auth    # open the printed URL, log in as the bot account
.venv/bin/python -m bot console # play locally, no Twitch
.venv/bin/python -m bot         # run in the configured channel
```

**Server (later):**
- Copy the project and `data/.tio.tokens.json`.
- Install a systemd unit:
  ```ini
  [Service]
  ExecStart=/opt/offline-chat-bot/.venv/bin/python -m bot
  WorkingDirectory=/opt/offline-chat-bot
  Restart=on-failure
  RestartSec=30
  RestartPreventExitStatus=2 3
  [Unit]
  StartLimitIntervalSec=0
  ```
- `?bot shutdown` exits with code 0, so it stays down. A crash or lost connection restarts
  after 30 s and keeps retrying, so a long Twitch outage heals on its own. Config errors (2) and
  login problems (3) are never restarted. (Revised 2026-10-04: the earlier "at most 5 restarts in
  10 minutes" would have left the bot stopped for good after an outage.)
- Anyone with server access restarts it with `sudo systemctl start offline-chat-bot`.
- Run only one instance at a time, or every command is answered twice.

**Going live in jasontheween's chat:** the contact mods the bot account. Set
`channel = "jasontheween"` and restart.

## 16. Phase 1 done when

- All tests in section 14, parts 1 and 2, pass.
- The live checklist in section 14, part 3, passes in Robert's channel.
- `python -m bot console` lets a person play both games and all quick commands with no
  Twitch account.
- A README covers setup, the commands, and the server move.
- Robert has reviewed and approved `content/words/streamers.txt` and `content/words/games.txt`.

## 17. Later phases: captured requirements

These are not designed here. They are listed so Phase 1 does not block them. Phases 2-4 now
have their own design specs (`2026-10-04-offline-chat-bot-phase2-design.md`, `-phase3-`, and
`-phase4-`), which supersede these notes.

- **`?trivia [category] [difficulty]`, `?hint`, `?skip`:** personal. Open Trivia DB supplies
  categories and difficulties. Easy questions are multiple choice and medium/hard are typed
  answers (Robert, 2026-10-04). `?hint` uses the in-game command support built in Phase 1.
- **`?riddle`:** personal. A bundled riddle list with forgiving answer matching. Only the keyword, or
  typo tolerance.
- **`?familyfeud`:** dropped by Robert (2026-10-04).
- **`?higherlower`:** personal streak game. Needs search-popularity numbers for pairs of terms,
  as a bundled dataset.
- **`?rng`, `?rng today|top|me|<user>`:** one roll from 0 to 1,000,000 per user per UTC day,
  using `daily_uses`. RNGdle's 203 badge rules are not public, so we write our own badge rules
  (palindromes, repeated digits, primes, meme numbers, and so on).
- **`?ascii <emote> [emote2] | -t <text> | -bt <bottom_text>`:** fetch emote images from the
  Twitch, 7TV, BTTV, and FFZ APIs, then render braille art within 500 characters. Needs
  Pillow.
- **`?chatsummary`, `?cs continue`:** keep the last 30 minutes of chat in memory only, never
  on disk, and summarize with an LLM API, which needs an API key and costs a little per call.
  `?cs continue` pages through a long summary.

- **Commands web page (optional, after the move to a server):** a page of command cards,
  like the reference bot's, generated from the registry's usage and description text, with
  `?help` linking to it.

## 18. Open items for the requester

- Point values and timers. The defaults above are adjustable in code or config.
