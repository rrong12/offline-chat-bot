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
USER_AGENT = "twitch-chat-games-bot (https://github.com/rrong12/twitch-chat-games-bot)"
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
NEEDS_OPTIONS = re.compile(r"\b(?:these|following|below|above|not|isn't|isnt|except|none of|released first"
                           r"|came first)\b", re.IGNORECASE)
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
    r"|high ?school (?:dxd|of the dead)|copulat\w*|courtesans?|testic\w*|morenatsu|breweries|beerbongs?|cider"
    r"|smokin|pills?|meth|poopy\w*|butthole|skinny dipping)\b|f\*\*\*",
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
    # final content check: drug, alcohol, crude or sexual references
    "b24b2ec6aa", "73250405bd", "c83119d927", "7b10c8f2f4", "42ad40f1e2", "bfe6f9c09a", "87cae92ada", "e624668a3d",
    "90da5b293c", "18ae936edf", "4a552ee754", "ee23034f51", "c2b44eb8fb", "92d20bd2ba", "efac808e7c", "de05405af0",
    "36c06af8e7", "77d6f53911", "4753e66b33", "0fc6d7fffd", "2422cc1091", "8a1e491575", "2bf8aaeeef", "dd2bd4c0c2",
    "d47d9e3117", "a2b28d227f", "7b60cf9d2c", "377aea9bec", "cda3197f67", "5f73d1ec4d", "b665177bd4", "cd05af5050",
    "48e8ef921d", "44137d054a", "5658e8c7ed", "3baa0215cc", "38402e4d13",
    # real tragedies asked as trivia; graphic horror or violence; political flashpoints
    "dfaa821c00", "9c4037dac2", "b80d786341", "3b391d6b14", "57cdce9ef6", "988d7a8357", "33242191b5", "15364ba138",
    "c39015cf72", "474216f98c", "85bd4e31e7", "d8117c67fa", "97127fb761", "c4652602c5", "34e3ac73be", "b9dc508a27",
    "7a08b7408e", "bd654a3270", "8ee79243f7", "e8fbc67d8b", "117834b7bc", "8418188f53", "cbc8dd1211", "2181f83cac",
    "4728ca8a42", "18c2806ac2", "6243576a4d", "47fdbadd42", "9ab5a7037e", "8e1992cc3e", "c8ae5e49b8", "1ef2cacab3",
    "e20b11145d", "0535be57ab",
    # wrong, disputed, outdated or misspelled
    "d36be0c6b3", "8f2e689589", "967cd0585b", "2f5173e788", "698b3fcb16", "6b04a405c0", "d957b5ebc1", "a087e2c231",
    "5b7e24e95e", "bd77947a49", "f05d2bd06c", "1c2b34a9d4", "e1865026f0", "a5a816db95", "9d1664bf8c", "1428729d73",
    "4a066cdd4f", "0c6bac2620", "5a3fe091bb", "53defe178e", "25c4d6db63", "c630b1ae24", "de84760186", "9fdf44eeb8",
    "e9e2cddf5c", "947d4001a4", "95cdbc54ea", "89263f34b5", "75dde8bc87", "ab4e2f29d5", "afe6a659c6", "dba06a6755",
    "57bed4fc07", "4c8184b541", "0503212f1e", "850e33e09a", "7956f9d43a", "795f421ab4", "4e57dcbb57", "976350cbe8",
    "ab0e72f545", "999384a64c", "4743af3412", "6bafaee378", "9e23bb25e9", "c66fffc21a", "cbd1fcc6c2", "0254780543",
    "e21b77c3b1", "266b7ab855",
    # typed questions that need their options or have several right answers
    "28b9949d5a", "23a7861c7f", "5be9b74e3d", "aa8b57cdf5", "f15f3a1dd2", "fc4692f4a1", "ae648bca41", "88f137cd88",
    "57d3a3b40e", "4aa43368fd", "b630474c0b", "39397a83f4", "6b31e0682e", "ea68f2ae68", "0e3eb290c0", "58f88e8388",
    "c2262c53f0", "83478bc71a", "ae367cae75", "8fea975549", "8910491353", "e2f1097a0e", "15c665e1a0",
    # stored answers in a form nobody types
    "4b4d08eda9", "73b2fb60a5", "78d25ae8e4", "8473a3da17", "56bd2fab46", "4169066b55", "27dbcb43fc", "f104bb9f27",
})
# Checked by hand: typed questions the "needs its options" or date filter would wrongly drop.
KEEP_IDS = frozenset({
    "95c4855061", "cc8223f928", "9a3af53f71", "60cde368d5", "e3b9706abe", "1df1830466", "af81c2f47c",
    "769ed5ba08",
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
