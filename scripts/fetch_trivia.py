"""Build bot/content/trivia.json from Open Trivia DB (https://opentdb.com, CC BY-SA 4.0).

Run once from the repo root: .venv/bin/python scripts/fetch_trivia.py
The API allows one request per 5 seconds per IP, so this takes several minutes. It only serves
verified questions. Easy questions keep their options (multiple choice); medium and hard ones
are kept only if the answer can reasonably be typed.

`--refilter` re-applies the filters below to the existing trivia.json without any network access.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.assets import Assets  # noqa: E402
from bot.fun import BlockedWords  # noqa: E402
from bot.text import normalize, strip_invisible  # noqa: E402

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
# Typed questions must make sense without seeing the options ("Which is not a country in Africa?").
NEEDS_OPTIONS = re.compile(r"\b(?:these|following|below|above|not|except|none of)\b", re.IGNORECASE)
# Typed answers nobody types the same way twice: dates with a month, long numbers, approximate figures.
_MONTH = (r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?"
          r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b")  # whole month names only: not "Mario Party 4"
MONTH_DATE = re.compile(rf"{_MONTH}.*\d|\d.*{_MONTH}", re.IGNORECASE)
LONG_NUMBER = re.compile(r"\d{5,}")
APPROXIMATE = re.compile(r"\b(?:approximately|roughly|about how|around how|estimated)\b", re.IGNORECASE)
# Topics that don't belong in a young, family-friendly chat, beyond the blocked-word list: drugs, alcohol,
# tobacco, sexual themes, self-harm, and a few fan-service anime titles.
MATURE_TOPICS = re.compile(
    r"\b(?:cocaine|heroin|cannabis|marijuana|thc|weed|drugs?|cartel|overdose|beer|brewery|vodka|whisk(?:e)?y|rum"
    r"|cocktails?|alcohol(?:ic)?|liquor|drunk|tobacco|cigarettes?|smoking|sex(?:ual|y)?|breasts?|harem|hot coffee"
    r"|stripper|suicide|kill (?:themselves|himself|herself|yourself)|schutzstaffel|to love-ru"
    r"|high ?school (?:dxd|of the dead)|copulat\w*|courtesans?|testicles?|morenatsu)\b",
    re.IGNORECASE,
)
# Checked and wrong, garbled, or out of date (see docs/superpowers/plans, Phase 2 execution log).
EXCLUDED_IDS = frozenset({
    "4be33db662", "5efa52ea29", "0d5228c649", "ac2967fc00", "0508b9f490", "358cd17e26", "01495b878f",
    "7732c495a3", "96ae8a7764", "5db409db5a",
    # second review: mature, need their options, out of date, unwinnable or too loose as typed questions
    "0a60a0d744", "9b1d123380", "8c394874bc", "4ed32265c4", "4edefa5a85", "975a5db97b", "c51570b283",
    "1059611032", "5561256950", "edee009d10", "6e0ed953fc", "9ea627bce0", "6addd9f6e9", "87737bf23e",
    "58c424f37e", "2a4bb44099",
})
# Checked by hand: typed questions the "needs its options" or date filter would wrongly drop.
KEEP_IDS = frozenset({
    "95c4855061", "cc8223f928", "9a3af53f71", "60cde368d5", "e3b9706abe", "c39015cf72", "1df1830466",
    "af81c2f47c", "cbd1fcc6c2", "769ed5ba08",
})
MAX_TYPED_WORDS = 3
MAX_TYPED_CHARS = 25
MAX_QUESTION = 300
MAX_EASY_TEXT = 400  # question plus options, so the multiple-choice message fits in one chat message
# Typed answers whose meaning is in symbols the matcher can't compare: C++, -40, 13.8, 2-3, 4/4, V = I*R.
MEANINGFUL_SYMBOLS = re.compile(r"[+#=*^<>°%?!♡♪]|\d\s*[.\-/:]\s*\d|(?:^|\s)-\s*\d")


def get(path: str, **params: object) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:  # includes HTTP 429 and dropped connections
            if attempt == 4:
                raise
            print(f"  retrying after {exc}", flush=True)
            time.sleep(DELAY * 2 ** (attempt + 1))
    raise AssertionError("unreachable")


def clean(text: str) -> str:
    """Invisible characters (soft hyphens, direction marks) removed and spaces collapsed."""
    return " ".join(strip_invisible(text).split())


def typeable(question: str, answer: str, qid: str = "") -> bool:
    lowered = question.lower()
    reviewed = qid in KEEP_IDS
    return (
        len(answer.split()) <= MAX_TYPED_WORDS
        and len(answer) <= MAX_TYPED_CHARS
        and normalize(answer) != ""  # "♡♪!?" or "?:" can't be typed as a guess
        and not MEANINGFUL_SYMBOLS.search(answer)
        and not MONTH_DATE.search(answer)
        and not LONG_NUMBER.search(answer.replace(",", ""))
        and not (APPROXIMATE.search(lowered) and re.search(r"\d", answer))
        and (reviewed or not NEEDS_OPTIONS.search(question))
    )


def clear_options(options: list[str]) -> bool:
    """Easy options must read differently once spaces and case are ignored, and none may be a lone
    letter, which a player would read as A-D ("E", "A", "I", "O")."""
    compact = [normalize(o).replace(" ", "") for o in options]
    lone_letter = any(len(c) == 1 and c.isalpha() for c in compact)
    return len(set(compact)) == len(options) and "" not in compact and not lone_letter


def keep(entry: dict, blocked: BlockedWords) -> bool:
    """Every rule a question must pass, used both while downloading and by --refilter."""
    question, answer = entry["question"], entry["answer"]
    texts = [question, answer, *entry.get("wrong", [])]
    if entry["id"] in EXCLUDED_IDS or len(question) > MAX_QUESTION:
        return False
    if any(blocked.found_in(t) or MATURE_TOPICS.search(t) for t in texts):
        return False
    if entry["difficulty"] == "easy":
        options = [answer, *entry["wrong"]]
        return sum(len(t) + 4 for t in options) + len(question) <= MAX_EASY_TEXT and clear_options(options)
    return typeable(question, answer, entry["id"])


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


def question_key(question: str) -> str:
    """Questions that differ only in punctuation or case are the same question."""
    return re.sub(r"[^a-z0-9]", "", question.lower())


def tidy(entry: dict) -> dict:
    entry = dict(entry, question=clean(entry["question"]), answer=clean(entry["answer"]))
    if "wrong" in entry:
        entry["wrong"] = [clean(w) for w in entry["wrong"]]
    return entry


def refilter() -> None:
    blocked = BlockedWords.load(Assets())
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    before = len(payload["questions"])
    kept, keys = [], set()
    for q in map(tidy, payload["questions"]):
        if keep(q, blocked) and question_key(q["question"]) not in keys:
            keys.add(question_key(q["question"]))
            kept.append(q)
    payload["questions"] = kept
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"kept {len(payload['questions'])} of {before} questions in {OUT}")


def main() -> None:
    if "--refilter" in sys.argv[1:]:
        refilter()
        return
    blocked = BlockedWords.load(Assets())
    token = get("api_token.php", command="request")["token"]
    questions: list[dict] = []
    seen: set[str] = set()  # question keys
    for ours, ids in CATEGORIES.items():
        for difficulty in DIFFICULTIES:
            raw = [q for category_id in ids for q in fetch_all(token, category_id, difficulty)]
            kept = 0
            for q in raw:
                question = clean(urllib.parse.unquote(q["question"]))
                answer = clean(urllib.parse.unquote(q["correct_answer"]))
                wrong = [clean(urllib.parse.unquote(a)) for a in q["incorrect_answers"]]
                qid = hashlib.sha1(question.encode()).hexdigest()[:10]
                entry = {"id": qid, "category": ours, "difficulty": difficulty, "question": question, "answer": answer}
                if difficulty == "easy":
                    entry["wrong"] = wrong
                if question_key(question) in seen or not keep(entry, blocked):
                    continue
                seen.add(question_key(question))
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
