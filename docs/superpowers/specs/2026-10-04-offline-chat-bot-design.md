# Offline Chat Bot: Design (Phase 1)

Date: 2026-10-04
Status: draft, awaiting review

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
| **1 (this spec)** | Core (Twitch connection, admin controls, activity log, outbox, stats database, game manager), `?leaderboard`, `?gamestats`, `?scramble`, `?hangman` (+ `?g`), `?skip`, `?8ball`, `?coinflip`, `?catfact`, `?dogfact`, `?fact`, `?dadjoke`, `?cookie` |
| 2 | `?trivia` (+ `?hint`), `?riddle`, `?familyfeud` / `?feud` / `?ffskip`, `?higherlower` |
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
| One game at a time | Yes, with a cooldown between games | Keeps a busy chat readable. |
| Hangman guessing | Explicit `?g <letter>` or `?g <answer>`; plain chat is ignored | "W" and "L" are constant reactions in Jason's chat and would otherwise count as guesses. |
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
   no Chat Bot badge, 1 msg/s, slow mode applies") and continue. This lets the bot run in a
   test channel before it is modded.
5. Subscribe over WebSocket to `ChatMessageSubscription(broadcaster_user_id=<channel>,
   user_id=<bot>)` using the bot token. This must happen within 10 s of the socket's welcome
   message; TwitchIO handles the timing.
6. Post nothing on startup, and log `startup`.

### Limits the bot must respect
- Messages are capped at 500 characters, so the outbox truncates at a word boundary.
- The send rate is 100 per 30 s as a mod (20 per 30 s and 1/s otherwise). The outbox stays
  far below this (section 9).
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
│   ├── commands.py          command registry: name → handler, aliases, permission, cooldowns
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
│   │   ├── manager.py       GameManager: lifecycle, timers, cooldown, skip votes, scoring
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
    async def run(self, on_message: Callable[[ChatMessage], Awaitable[None]]) -> None: ...
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
GameManager.on_message (if a game is active) → handlers produce text → Outbox → Connector.send`.

A single 1-second tick loop calls `GameManager.tick(now)` and the log-retention check. Games
never create their own timers, so tests can drive time directly.

## 5. Commands (Phase 1)

Cooldowns, unless noted: each command has a **10 s per-user** cooldown and a **5 s global**
cooldown. A command on cooldown is silently ignored. Control commands (`?bot ...`,
`?stopgame`), `?skip`, and in-game commands such as `?g` skip these cooldowns. `?skip` is
limited to one vote per user per round, and each game enforces its own limits on its
in-game commands. Quick-command answers use Twitch's
threaded reply (`reply_to`). Game announcements are plain messages.

| Command | Who | Behavior |
|---|---|---|
| `?bot off` | controller | Pause. Cancels the active game (outcome `stopped`, no points), persists `paused=1`, replies "Bot paused by \<name\>. `?bot on` to resume." |
| `?bot on` | controller | Resume and persist `paused=0`. |
| `?bot status` | controller | "ON/PAUSED · up 3h12m · game: scramble (21s left) · v0.1.0". Works while paused. |
| `?bot shutdown` | controller | Sends "Shutting down (requested by \<name\>)." at priority, stops the game, logs `admin`/`shutdown` with the user, flushes the outbox (max 3 s), closes the connector, exits with code 0. |
| `?stopgame` | controller | Cancels the active game. Outcome `stopped`, no points, cooldown starts. |
| `?skip` | anyone, in a game | Records one skip vote per user per round. When `skip_votes` (default 3) distinct users have voted, the answer is revealed and the round ends with outcome `skipped` and no points. Each vote is acknowledged in a coalesced message ("Skip 2/3"). |
| `?leaderboard [game] [limit]` | anyone | Top N (default 5, clamped 1 to 10) by points for one game, or across all games when no game is named. "Top 5 scramble: 1. a (120) 2. b (98) …". Ties go to more wins, then login. A numeric argument is the limit. |
| `?gamestats [game] [username]` | anyone | With no game: totals plus a per-game breakdown (wins, played, points), truncated to fit. With a game: wins, played, points, and rank in that game. If the first argument matches a game name it is the game; otherwise it is a username. A leading `@` is stripped. Unknown user: "No stats for \<name\> yet." Defaults to the caller. |
| `?scramble [category]` | anyone | Start Scramble (section 7). With no category, one is picked at random and named in the opening message. |
| `?scramble categories` | anyone | "Scramble categories: animals, countries, …". Starts nothing and works while a game is running. |
| `?hangman [category]` | anyone | Start Hangman (section 7). Same random pick as Scramble when no category is given. |
| `?hangman categories` | anyone | Same as `?scramble categories`, for Hangman. |
| `?g <letter>` / `?g <answer>` | anyone, during Hangman | Guess a letter or the whole answer (section 7). Ignored when no Hangman game is running. |
| `?8ball [question]` | anyone | One of 20 classic answers from `content/8ball.txt`. The question is not echoed. |
| `?coinflip` | anyone | "Heads" or "Tails". |
| `?catfact` | anyone | `GET https://catfact.ninja/fact` → `fact`. |
| `?dogfact` | anyone | `GET https://dogapi.dog/api/v2/facts` → `data[0].attributes.body`. |
| `?fact` | anyone | `GET https://uselessfacts.jsph.pl/api/v2/facts/random?language=en` → `text`. |
| `?dadjoke` | anyone | `GET https://icanhazdadjoke.com/` with `Accept: application/json` and a descriptive `User-Agent` → `joke`. |
| `?cookie` | anyone | Once per UTC day: a random fortune from `content/fortunes.txt`. If already used: "You already opened today's cookie. Next one in 3h 12m (00:00 UTC)." |
| `?cookie give <username>` | anyone | Uses the giver's daily cookie on someone else: "@a gave @b a fortune cookie: …". The username must match `^[A-Za-z0-9_]{3,25}$` and exist (`lookup_user`). Giving to yourself is not allowed. Counts as the giver's cookie for the day; the recipient's own cookie is unaffected. |

**Facts and jokes:** all four APIs were verified working on 2026-10-04. Each call has a
3-second timeout. On failure, or if the result is over 400 characters, the bot uses a random
line from the matching `content/fallback_*.txt` list (about 50 entries each).

Starting a game while one is running gets "A \<game\> game is already running." During the
cooldown it gets "Next game in \<n\>s." These replies are subject to the per-user cooldown.

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

### GameManager rules
- **Start:** `?<name> [category]` starts a game when none is active and the cooldown is over.
  - With no category, one is chosen at random, and the opening message names it.
  - An unknown category gets the category list and starts nothing.
- **Category list:** `?<name> categories` replies with the game's categories and starts
  nothing. It is handled before the start rules, so it works during a game or the cooldown,
  and it uses the normal command cooldowns. `categories` is reserved and cannot be a category
  name.
- **In-game commands:** while a game is active, a prefixed message whose command is in the
  game's `commands` goes to `on_command` instead of the global registry. When no game
  declares it, the command is ignored.
- **Participation:** the game decides what counts as an attempt. `on_message` and
  `on_command` return `None` for ordinary chatter or rejected input, and an `Outcome`,
  possibly empty, for an attempt. Only attempts mark
  the sender as a player of the round, so people just chatting during a game do not inflate
  "played" in `?gamestats`.
- **Timers:** `tick(now)` calls `on_tick(elapsed)`. At `time_limit` it calls `on_timeout()`.
- **Finishing:** when an `Outcome` has `finished=True`, the manager:
  1. writes the round and its players (awards and winners) in one transaction,
  2. logs `game_end`,
  3. sends the messages,
  4. starts the cooldown (`game_cooldown`, default 30 s).
- **Skip and stop:** handled in the manager. They call `reveal()` and record outcome
  `skipped` or `stopped`, with no points.
- **Errors:** an exception from game code is logged with a traceback. The round is recorded
  as `stopped` with no points, and chat gets "Game ended due to an error." The bot keeps
  running.
- **Registration:** games are listed in `config.toml` under `[games] enabled = [...]`. Adding
  a game takes one module plus one config entry.

### Answer normalization (`text.normalize`)
1. Unicode NFKC.
2. Lowercase.
3. Remove invisible characters, including the U+E0000 tag that Chatterino and 7TV clients
   append to repeated messages, and zero-width characters.
4. Replace punctuation with spaces.
5. Collapse whitespace and trim.

An answer matches only when the whole normalized message equals the normalized answer.
Substrings do not count, which avoids false positives in a busy chat.

## 7. Phase 1 games

### Scramble
- **Answer:** a random word from `content/words/<category>.txt`, 4 to 10 letters, letters
  only. The displayed scramble must differ from the word; reshuffle until it does.
- **Messages:**
  - start: "🔤 Unscramble (animals): LGRATIOAL, 45s".
  - Hint 1 at 15 s shows the first and last letters (`A _ _ _ _ _ _ _ R`).
  - Hint 2 at 30 s reveals about half of the letters, chosen at random but stable.
- **Attempt:** a message that normalizes to a single word with the same number of letters as
  the answer. Other chatter is ignored.
- **Win:** the first message whose normalized text equals the word. Points are 10 before any
  hint, 7 after hint 1, and 4 after hint 2. "✅ \<name\> got it: ALLIGATOR (+7)".
- **Timeout:** at 45 s, "⏰ Time's up! It was ALLIGATOR." No points.

### Hangman
- **Answer:** a random entry from `content/words/<category>.txt`. It may be a short phrase;
  spaces and punctuation are shown, and only letters are hidden.
- **Start:** "🪢 Hangman (animals): _ _ _ _ _ _ _ _ _ · guess with ?g <letter> or ?g <answer> · 6 lives, 120s".
- **Board:** `_ A _ _ M A N | wrong: E T R (3/6)`. Sent with `coalesce_key="hangman-board"`, so
  bursts of guesses produce one up-to-date board instead of a backlog.
- **Guessing:** only through `?g`. Plain chat messages are ignored, so "W" and "L"
  reactions never count.
  - `?g <letter>`, one letter A to Z, is a letter guess.
  - `?g <answer>`, anything longer, is a solve attempt.
  - Each user may use `?g` at most once every 5 s.
  - Repeated letters are ignored.
  - A correct new letter earns its guesser 1 point, held until the round ends.
  - A wrong letter costs one of 6 lives.
- **Attempt:** any accepted `?g`.
- **Solve:** `?g <answer>` that equals the full answer, normalized, solves it. Wrong solve
  attempts cost nothing, so griefers cannot burn lives with junk words.
- **Win:** the round is won by a full solve, or when the last hidden letter is revealed. The
  winner (the solver, or whoever revealed the last letter) gets 10 points. Held letter points
  are awarded too.
- **Loss:** after 6 wrong letters or 120 s, "💀 The word was …". Nobody gets points, held
  letter points included.

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

- **Rate:** a token bucket with a sustained rate of 1 message/s and a burst of 3. As a mod the
  bot could send about 3/s; the margin is intentional.
- **Queue:** at most 20 messages. When it is full, new normal-priority messages are dropped
  and logged (`send_dropped`). Priority messages (admin replies, shutdown notice) go to the
  front.
- **Coalescing:** a message with a `coalesce_key` replaces any unsent queued message with the
  same key.
- **Truncation:** messages are cut at the last word boundary that fits 500 characters, with
  `…` appended.
- **Send results:** if Twitch returns `is_sent=false`, the `drop_reason` code and message are
  logged. No retries.
- **Shutdown:** the queue is flushed for up to 3 s.

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
| `game_start` | round, game, category, started_by |
| `game_end` | round, game, outcome, winners, awards |
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
game_cooldown_seconds = 30
skip_votes = 3

[games]
enabled = ["scramble", "hangman"]

[outbox]
rate_per_second = 1
burst = 3
max_queue = 20

[logs]
retention_days = 30
```

The config is validated at startup. An invalid value exits with code 2 and a message naming
the bad key.

## 13. Error handling

| Failure | Behavior |
|---|---|
| WebSocket drop or reconnect | TwitchIO reconnects, honoring Twitch's reconnect message and the keepalive timeout. The bot logs `disconnected` and `reconnected`. Game timers keep running. Sending uses HTTP (Helix), not the socket, so a timeout message still goes out during the outage. |
| Token refresh fails or token revoked | Log "re-run `python -m bot auth`", exit with code 3. The server's service does not restart on code 3. |
| Channel not found | Exit code 2 with a message. |
| Bot not a mod | Warning only (section 3). |
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
   - stats queries on a temporary database;
   - the daily-use UTC boundary;
   - Scramble and Hangman with a seeded RNG and explicit `now` and `elapsed` values;
   - GameManager start, cooldown, skip votes, stop, and error-in-game.
2. **Full-flow tests** drive `BotCore` through a scripted `ConsoleConnector`. Scenarios:
   - Start scramble, a wrong answer, a right answer, points awarded, `?leaderboard` shows them.
   - Hangman win and loss through `?g`. Plain one-letter messages ("W") are ignored.
   - Three `?skip` votes.
   - A non-mod's `?bot shutdown` is ignored. A mod's `?bot off` blocks games; `?bot on`
     restores them.
   - Paused state survives a restart.
   - Shared-chat messages are ignored.
   - `?cookie` twice on the same day, and again after UTC midnight.
   - A fact API timeout falls back to the bundled list.
3. **Live checklist in Robert's channel**, with the bot modded there, Robert's account, and a
   second non-mod account:
   - The startup log shows `is_mod=true`, and bot messages carry the Chat Bot badge.
   - Play both games to win, timeout, and skip, and check `?gamestats` and `?leaderboard`.
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
  RestartSec=5
  RestartPreventExitStatus=2 3
  [Unit]
  StartLimitIntervalSec=600
  StartLimitBurst=5
  ```
- `?bot shutdown` exits with code 0, so it stays down. A crash restarts after 5 s, at most 5
  times in 10 minutes.
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

## 17. Later phases: captured requirements

These are not designed here. They are listed so Phase 1 does not block them.

- **`?trivia [category] [difficulty]`, `?hint`, `?skip` (3 votes):** Open Trivia DB supplies
  categories and difficulties. `?hint` uses the in-game command support built in
  Phase 1.
- **`?riddle`:** a bundled riddle list with forgiving answer matching. Only the keyword, or
  typo tolerance.
- **`?familyfeud` / `?feud`, `?ffskip` (3 votes):** needs a survey dataset of answers with
  counts. Several answers per round, with points scaled by popularity. Sourcing the data is
  the main work.
- **`?higherlower`:** needs search-popularity numbers for pairs of terms, as a bundled
  dataset. Chat votes higher or lower.
- **`?rng`, `?rng today|top|me|<user>`:** one roll from 0 to 1,000,000 per user per UTC day,
  using `daily_uses`. RNGdle's 203 badge rules are not public, so we write our own badge rules
  (palindromes, repeated digits, primes, meme numbers, and so on).
- **`?ascii <emote> [emote2] | -t <text> | -bt <bottom_text>`:** fetch emote images from the
  Twitch, 7TV, BTTV, and FFZ APIs, then render braille art within 500 characters. Needs
  Pillow.
- **`?chatsummary`, `?cs continue`:** keep the last 30 minutes of chat in memory only, never
  on disk, and summarize with an LLM API, which needs an API key and costs a little per call.
  `?cs continue` pages through a long summary.

## 18. Open items for the requester

- Point values and timers. The defaults above are adjustable in code or config.
