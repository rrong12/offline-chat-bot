# Offline Chat Bot

A Twitch chat bot for jasontheween's offline chat: personal chat games (Scramble, Hangman,
Trivia, Riddle, Higher or Lower), quick fun commands, per-game points with leaderboards, mod
controls (pause, resume, shut down), and a daily activity log. Designs:
`docs/superpowers/specs/` (Phase 1 core, Phase 2 games).

Games are personal: `?scramble` starts **your** game, only your answers count, and the bot
answers you in threaded replies. Many people can play at once (25 games by default), each
person runs one game at a time, and new games are refused ("try again in a moment") while the
bot's outgoing messages are backed up.

## Commands

| Command | Who | What it does |
|---|---|---|
| `?help` / `?commands`, `?help <command>` | anyone | List commands, or explain one |
| `?scramble [category]`, `?scramble categories` | anyone | Your own word to unscramble: type the answer; `?hint` for a hint (10/7/4 points) |
| `?hangman [category]`, `?hangman categories` | anyone | Your own Hangman; guess with `?g <letter>` or `?g <answer>` |
| `?trivia [category] [easy\|medium\|hard]`, `?trivia categories` | anyone | Your own trivia question. Easy is multiple choice (`?g A`-`D`, 5 points); medium and hard are typed (`?g <answer>`, 3 guesses, `?hint`; medium 10/7/4, hard 15/10/6 points). Questions from Open Trivia DB (CC BY-SA 4.0) |
| `?riddle` | anyone | Your own riddle: `?g <answer>`, 3 guesses, `?hint` for a clue then the letter count (10/7/4 points) |
| `?higherlower` / `?hl` | anyone | Does the next thing get more monthly Wikipedia views? `?g higher` or `?g lower`; 1 point per right answer, one miss ends the streak |
| `?skip` | anyone | End your current game (no points) |
| `?leaderboard [game] [1-10]` | anyone | Top players by points |
| `?gamestats [game] [username]` | anyone | Wins, games played, points |
| `?8ball`, `?coinflip`, `?catfact`, `?dogfact`, `?fact`, `?dadjoke` | anyone | Quick fun |
| `?cookie`, `?cookie give <username>` | anyone | Daily fortune cookie (resets 00:00 UTC) |
| `?bot off` / `?bot on` / `?bot status` | mods, broadcaster, owners | Pause, resume, check. `?bot off` ends every running game with no points, and while paused the bot ignores everything except `?bot` from a mod |
| `?bot shutdown` | mods, broadcaster, owners | Stop the bot process. Only someone with access to the machine can start it again |
| `?stopgame` | mods, broadcaster, owners | End all running games with no points |

Scramble and Hangman categories: animals, countries, food, games, general, streamers. Trivia
categories: animals, anime, games, general, geography, history, movies, music, science, sports, tv.

A player doesn't get the same trivia question or riddle again within their last 50.

## Install

```
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Any Python from 3.11 to 3.13 works.

## Try it without Twitch

```
.venv/bin/python -m bot console
```

Type lines like `alice: ?scramble animals`. A leading `@` makes the user a mod (`@mod: ?bot off`).
Console mode keeps its own database under `data/console/`, separate from the real one.

On macOS, the python.org installer ships without root certificates, so HTTPS would fail. The
bot detects this at startup and uses the `certifi` certificate bundle automatically.

## Set up on Twitch (one time)

1. **Bot account:** create a new Twitch account for the bot and verify its email.
2. **Twitch app:** at https://dev.twitch.tv/console, register an application (Twitch requires
   two-factor authentication on the account that registers it).
   - OAuth Redirect URL: `http://localhost:4343/oauth/callback` (exactly).
   - Category: Chat Bot. Client type: Confidential.
   - Copy the Client ID and create a Client Secret.
3. **Secrets:** `cp .env.example .env`, then fill in `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`.
   `.env` holds secrets: never share or commit it (it's git-ignored).
4. **Your numeric user ID** goes in `OWNER_IDS`. It's a number, not your username. To look it up
   (replace `yourname`):
   ```
   source .env
   TOKEN=$(curl -s -X POST "https://id.twitch.tv/oauth2/token?client_id=$TWITCH_CLIENT_ID&client_secret=$TWITCH_CLIENT_SECRET&grant_type=client_credentials" | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
   curl -s -H "Client-Id: $TWITCH_CLIENT_ID" -H "Authorization: Bearer $TOKEN" "https://api.twitch.tv/helix/users?login=yourname"
   ```
   The `"id"` in the answer is your user ID.
5. **Log the bot in:** run `.venv/bin/python -m bot auth`. Open the printed URL in a browser where
   you're logged in as the **bot** account and approve. Put the printed `BOT_ID=...` line in `.env`.
   The login is saved in `data/.tio.tokens.json`. Never share or commit that file.
6. **Channel:** set `channel` in `config.toml` to the channel the bot should join.
7. **Mod the bot** in that channel (`/mod <botaccount>` in its chat). Without mod status the bot
   still runs, but it sends more slowly (0.6 messages per second, under Twitch's non-mod limit),
   slow mode applies, and it won't show the Chat Bot badge. The startup log says `is_mod` either
   way. If a mod unmods the bot while it runs, it switches to the slower mode by itself.

## Run

```
.venv/bin/python -m bot
```

- Ctrl+C stops it cleanly.
- `?bot shutdown` from a mod also stops it, with exit code 0.

**Exit codes:**
- 0: stopped on purpose.
- 1: crashed.
- 2: config problem (the message names the setting).
- 3: the Twitch login needs redoing (`python -m bot auth`).
- 130: Ctrl+C before the bot finished starting.

## Settings

- `config.toml` holds the non-secret settings: channel, prefix, cooldowns, enabled games, how
  many games can run at once, the busy threshold, the send rate, and log retention.
- `.env` holds the secrets.
- The word lists are plain text in `bot/content/words/`, one entry per line. Adding a file adds
  a category.
- `bot/content/words/SOURCES.md` records where each streamer and game name was verified.

## Data and logs

- `data/bot.db` (SQLite) holds points, rounds, daily cookies, and the paused flag. The paused
  flag survives restarts.
- `data/logs/activity-YYYY-MM-DD.jsonl` is one file per UTC day. It records commands, game
  starts and ends, admin actions (who paused or shut down the bot), connection events, and
  errors. Ordinary chat is never logged. Files older than 30 days are deleted.

## Move to a server

1. Copy the project folder to the server (for example `/opt/offline-chat-bot`), including
   `.env` and `data/.tio.tokens.json`.
2. On the server: `python3 -m venv .venv && .venv/bin/pip install -e .` (any Python 3.11-3.13).
3. Create a user for the bot (`sudo useradd -r chatbot`), give it the folder, and make the two
   secret files readable only by it:
   ```
   sudo chown -R chatbot /opt/offline-chat-bot
   sudo chmod 600 /opt/offline-chat-bot/.env /opt/offline-chat-bot/data/.tio.tokens.json
   ```
4. `sudo cp deploy/offline-chat-bot.service /etc/systemd/system/`, then
   `sudo systemctl daemon-reload && sudo systemctl enable --now offline-chat-bot`.
5. **How it behaves on the server:**
   - **After a crash or a lost connection:** restarts after 30 seconds and keeps retrying, so a
     long Twitch outage heals on its own. A config error (exit 2) or a needed re-login (exit 3)
     is never restarted, because those need a person.
   - **After `?bot shutdown`:** stays down until someone with server access runs
     `sudo systemctl start offline-chat-bot`.
   - **Logs:** `journalctl -u offline-chat-bot -f`.
6. **Run only one copy of the bot at a time.** If it's running on both your laptop and the
   server, every command is answered twice.
7. **If it stops with exit 3 (login needed):** the login page needs a browser, which a server
   doesn't have. Either run `python -m bot auth` on your laptop and copy the new
   `data/.tio.tokens.json` to the server (then `chmod 600` it and restart the service), or tunnel
   the login port with `ssh -L 4343:localhost:4343 <server>` and run `auth` on the server.

## Go live in jasontheween's chat

1. A channel mod runs `/mod <botaccount>` there.
2. Set `channel = "jasontheween"` in `config.toml`.
3. Restart the bot (`sudo systemctl restart offline-chat-bot` on the server).

## Tests

```
.venv/bin/pytest
```

## Content

- Trivia questions come from [Open Trivia DB](https://opentdb.com/) (CC BY-SA 4.0; see
  `bot/content/TRIVIA_CREDITS.md`). `scripts/fetch_trivia.py` rebuilds `bot/content/trivia.json`
  (it takes several minutes because of the API's rate limit).
- Riddles (`bot/content/riddles.json`) were written for this bot and checked by a second reviewer.
- Higher or Lower uses last month's English Wikipedia page views. Edit
  `scripts/higherlower_terms.txt` and run `scripts/fetch_pageviews.py` to change the terms or
  refresh the numbers.
- `tests/test_content.py` checks every content file's rules (lengths, blocked words, clues that
  don't give the answer away).
