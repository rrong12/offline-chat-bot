# Offline Chat Bot

A Twitch chat bot for jasontheween's offline chat: personal chat games (Scramble, Hangman),
quick fun commands, per-game points with leaderboards, mod controls (pause, resume, shut down),
and a daily activity log. Design: `docs/superpowers/specs/2026-10-04-offline-chat-bot-design.md`.

Games are personal: `?scramble` starts **your** game, only your answers count, and the bot
answers you in threaded replies. Many people can play at once (25 games by default), each
person runs one game at a time, and new games pause while the bot's outgoing messages are
backed up.

## Commands

| Command | Who | What it does |
|---|---|---|
| `?help` / `?commands`, `?help <command>` | anyone | List commands, or explain one |
| `?scramble [category]`, `?scramble categories` | anyone | Your own word to unscramble: type the answer; `?hint` for a hint (10/7/4 points) |
| `?hangman [category]`, `?hangman categories` | anyone | Your own Hangman; guess with `?g <letter>` or `?g <answer>` |
| `?skip` | anyone | End your current game (no points) |
| `?leaderboard [game] [1-10]` | anyone | Top players by points |
| `?gamestats [game] [username]` | anyone | Wins, games played, points |
| `?8ball`, `?coinflip`, `?catfact`, `?dogfact`, `?fact`, `?dadjoke` | anyone | Quick fun |
| `?cookie`, `?cookie give <username>` | anyone | Daily fortune cookie (resets 00:00 UTC) |
| `?bot off` / `?bot on` / `?bot status` | mods, broadcaster, owners | Pause, resume, check |
| `?bot shutdown` | mods, broadcaster, owners | Stop the bot process. Only someone with access to the machine can start it again |
| `?stopgame` | mods, broadcaster, owners | End all running games with no points |

Categories: animals, countries, food, games, general, streamers.

## Try it without Twitch

```
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m bot console
```

Type lines like `alice: ?scramble animals`. A leading `@` makes the user a mod (`@mod: ?bot off`).
Console mode keeps its own database under `data/console/`, separate from the real one.

On macOS, the python.org installer ships without root certificates, so HTTPS would fail. The
bot detects this at startup and uses the `certifi` certificate bundle automatically.

## Set up on Twitch (one time)

1. **Bot account:** create a new Twitch account for the bot and verify its email.
2. **Twitch app:** at https://dev.twitch.tv/console, register an application.
   - OAuth Redirect URL: `http://localhost:4343/oauth/callback` (exactly).
   - Category: Chat Bot. Client type: Confidential.
   - Copy the Client ID and create a Client Secret.
3. **Secrets:** `cp .env.example .env`, then fill in `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, and
   your own Twitch user ID in `OWNER_IDS`.
4. **Log the bot in:** run `.venv/bin/python -m bot auth`. Open the printed URL in a browser where
   you're logged in as the **bot** account and approve. Put the printed `BOT_ID=...` line in `.env`.
   The login is saved in `data/.tio.tokens.json`. Never share or commit that file.
5. **Channel:** set `channel` in `config.toml` to the channel the bot should join.
6. **Mod the bot** in that channel (`/mod <botaccount>` in its chat). Without mod status the bot
   still runs, but it can only send 1 message per second, slow mode applies, and it won't show
   the Chat Bot badge. The startup log says `is_mod` either way.

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
2. On the server: `python3.12 -m venv .venv && .venv/bin/pip install -e .`
3. Create a user for the bot (`sudo useradd -r chatbot`) and give it the folder
   (`sudo chown -R chatbot /opt/offline-chat-bot`).
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

## Go live in jasontheween's chat

1. A channel mod runs `/mod <botaccount>` there.
2. Set `channel = "jasontheween"` in `config.toml`.
3. Restart the bot.

## Tests

```
.venv/bin/pytest
```
