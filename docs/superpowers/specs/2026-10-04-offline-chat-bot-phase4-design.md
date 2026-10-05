# Offline Chat Bot: Phase 4 Design (?ascii, ?chatsummary)

Date: 2026-10-04
Status: draft for Robert's review. The decisions come from the design conversation on 2026-10-04.

## 1. `?ascii <emote>`

- **Sources:** Twitch emotes only, global plus the channel's (Robert's choice). Emote names come from the Helix "Get Global Emotes" and "Get Channel Emotes" endpoints, using the app token. They're cached and refreshed every 6 hours, and matched case-sensitively, as on Twitch.
- **Rendering:**
  - Download the emote's static image, using the first frame of an animated one.
  - Convert it with Pillow to braille art, **30 characters wide by up to 15 rows**, the most that fits one 500-character message. This is the default because Robert wasn't sure; `[ascii] width` and `[ascii] rows` adjust it.
  - Each braille character is 2×4 pixels, drawn from luminance plus transparency. Rows are padded with the blank braille character and separated by spaces, so they line up at Twitch's normal chat width.
- **Limits:** a 60-second chat-wide cooldown, and `[ascii] enabled` to switch it off (mods may treat emote art as spam). An unknown emote gets "Twitch emote not found." without echoing the name.
- **Not built:** the reference bot's `-t <text>` and `-bt` text modes, since they repeat what the user typed. Also no 7TV, BTTV or FFZ.
- **New dependency:** Pillow. In console mode there are no Twitch emotes, so the command explains that it only works on Twitch.

## 2. `?chatsummary` / `?cs`, `?cs continue`

- **Model:** a free OpenRouter model (Robert's choice). It's chosen at build time from OpenRouter's current free models, and `[chatsummary] model` can change it. The key goes in `.env` as `OPENROUTER_API_KEY`; without a key, the command says it's not set up.
- **Free-tier fit:**
  - Anyone can use it (Robert's choice), but the bot makes **a fresh summary at most once every 30 minutes**. Anyone asking in between gets the latest one again.
  - A daily cap of 45 calls stays under OpenRouter's 50 free requests per day.
  - If Robert later buys $10 of credits once, the limit becomes 1,000 a day and the interval can drop.
- **Input:**
  - A rolling buffer of the last 30 minutes of chat, **in memory only and never written to disk**. It holds at most 2,000 messages, newest kept.
  - It excludes the bot's own messages and commands.
  - Display names are included, so the summary can say who did what.
- **Safety:**
  - Chat text is untrusted. The prompt tells the model to treat it as data and to write a neutral 2-4 sentence summary with no links, @mentions or slurs.
  - The output goes through the same checks as fun-command API text, except the 400-character limit (paging handles length): control and invisible characters stripped, no links, no @mentions (names appear without @, so nobody is pinged), and the `BlockedWords` check. If it fails, the bot replies "Couldn't summarize right now."
  - **Privacy note** for the README: chat is sent to OpenRouter and the chosen provider. Turn on OpenRouter's setting that excludes providers who may train on your data.
- **Paging:** a long summary is split into 450-character pages, and `?cs continue` shows the next page of the latest summary.

## 3. Testing

- **Ascii:** braille conversion on fixture images (exact output for a tiny image), the width and row limits, the cooldown and the switch, and "unknown emote".
- **Chat summary:**
  - the buffer's time and size limits;
  - the cache interval and the daily cap;
  - paging;
  - output filtering;
  - a missing key.
  - The HTTP calls are faked, and a single live call is made only in the live checklist.

## 4. Later (not in Phase 4)

A web page listing every command, generated from the command registry (after the server move), and where to host the server.
