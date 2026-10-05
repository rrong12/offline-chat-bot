"""Build bot/content/trivia.json from Open Trivia DB (https://opentdb.com, CC BY-SA 4.0).

Run once from the repo root: .venv/bin/python scripts/fetch_trivia.py
The API allows one request per 5 seconds per IP, so this takes several minutes. It only serves
verified questions. Easy questions keep their options (multiple choice); medium and hard ones
are kept only if the answer can reasonably be typed.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.assets import Assets  # noqa: E402
from bot.fun import BlockedWords  # noqa: E402

API = "https://opentdb.com"
OUT = Path(__file__).resolve().parent.parent / "bot" / "content" / "trivia.json"
USER_AGENT = "offline-chat-bot (https://github.com/rrong12/offline-chat-bot)"
DELAY = 5.5  # seconds between requests

# Our category -> Open Trivia DB category IDs.
CATEGORIES: dict[str, tuple[int, ...]] = {
    "general": (9,),
    "games": (15,),
    "movies": (11,),
    "music": (12,),
    "tv": (14,),
    "anime": (31,),
    "sports": (21,),
    "science": (17, 18, 19),
    "geography": (22,),
    "history": (23,),
    "animals": (27,),
}
DIFFICULTIES = ("easy", "medium", "hard")
# Typed questions must make sense without seeing the options.
NEEDS_OPTIONS = ("of these", "of the following", "all of the above", "none of the")
MAX_TYPED_WORDS = 3
MAX_TYPED_CHARS = 25
MAX_QUESTION = 300
MAX_EASY_TEXT = 400  # question plus options, so the multiple-choice message fits in one chat message


def get(path: str, **params: object) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def typeable(question: str, answer: str) -> bool:
    lowered = question.lower()
    return (
        len(answer.split()) <= MAX_TYPED_WORDS
        and len(answer) <= MAX_TYPED_CHARS
        and not any(phrase in lowered for phrase in NEEDS_OPTIONS)
        and " NOT " not in f" {question} "
    )


def fetch_all(token: str, category_id: int, difficulty: str) -> list[dict]:
    """Every multiple-choice question for one category and difficulty (the token prevents repeats)."""
    found: list[dict] = []
    amount = 50
    while amount >= 1:
        time.sleep(DELAY)
        data = get("api.php", amount=amount, category=category_id, difficulty=difficulty,
                   type="multiple", encode="url3986", token=token)
        code = data["response_code"]
        if code == 0:
            found.extend(data["results"])
        elif code in (1, 4):  # fewer than `amount` left (with a token, Open Trivia DB may say either)
            amount //= 2
        elif code == 5:  # rate limited: wait and retry
            time.sleep(DELAY)
        else:
            raise RuntimeError(f"Open Trivia DB returned response code {code}")
    return found


def main() -> None:
    blocked = BlockedWords.load(Assets())
    token = get("api_token.php", command="request")["token"]
    questions: list[dict] = []
    seen: set[str] = set()
    for ours, ids in CATEGORIES.items():
        for difficulty in DIFFICULTIES:
            raw = [q for category_id in ids for q in fetch_all(token, category_id, difficulty)]
            kept = 0
            for q in raw:
                question = urllib.parse.unquote(q["question"]).strip()
                answer = urllib.parse.unquote(q["correct_answer"]).strip()
                wrong = [urllib.parse.unquote(a).strip() for a in q["incorrect_answers"]]
                qid = hashlib.sha1(question.encode()).hexdigest()[:10]
                texts = [question, answer, *wrong]
                if qid in seen or len(question) > MAX_QUESTION or any(blocked.found_in(t) for t in texts):
                    continue
                entry = {"id": qid, "category": ours, "difficulty": difficulty, "question": question, "answer": answer}
                if difficulty == "easy":
                    if len(question) + sum(len(t) + 4 for t in (answer, *wrong)) > MAX_EASY_TEXT:
                        continue
                    entry["wrong"] = wrong
                elif not typeable(question, answer):
                    continue
                seen.add(qid)
                questions.append(entry)
                kept += 1
            print(f"{ours:10} {difficulty:6} fetched {len(raw):4} kept {kept:4}", flush=True)
    payload = {
        "source": "Open Trivia DB (https://opentdb.com), licensed CC BY-SA 4.0",
        "fetched": date.today().isoformat(),
        "questions": questions,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"wrote {len(questions)} questions to {OUT}")


if __name__ == "__main__":
    main()
