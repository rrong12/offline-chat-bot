import pytest

from bot.text import (
    clean_username,
    fold_accents,
    format_duration,
    normalize,
    short_number,
    strip_article,
    strip_invisible,
    truncate,
    typo_match,
    within_one_edit,
)


def test_normalize_lowercases_and_collapses_spaces():
    assert normalize("  Hello   WORLD ") == "hello world"


def test_normalize_turns_punctuation_into_spaces():
    assert normalize("spider-man!") == "spider man"


def test_normalize_drops_chatterino_duplicate_tag():
    assert normalize("alligator \U000e0000") == "alligator"


def test_normalize_drops_zero_width_characters():
    assert normalize("alli" + chr(0x200B) + "gator") == "alligator"


def test_normalize_removes_combining_marks_instead_of_splitting_words():
    stroke = chr(0x0336)  # combining long stroke overlay: strikethrough "fancy text"
    assert normalize(f"h{stroke}e{stroke}l{stroke}l{stroke}o{stroke}") == "hello"


def test_normalize_removes_format_characters_mid_word():
    for invisible in (chr(0x00AD), chr(0x2066), chr(0xFE0F)):  # soft hyphen, directional isolate, variation selector
        assert normalize(f"alli{invisible}gator") == "alligator"


def test_normalize_keeps_accented_letters():
    assert normalize("Cafe" + chr(0x0301)) == "caf" + chr(0x00E9)  # NFKC composes the accent before marks are dropped


def test_normalize_applies_nfkc():
    assert normalize("ｆｕｌｌｗｉｄｔｈ") == "fullwidth"


def test_strip_invisible_keeps_visible_text():
    assert strip_invisible("?scramble\U000e0000") == "?scramble"


def test_truncate_leaves_short_text_alone():
    assert truncate("hi") == "hi"


def test_truncate_cuts_at_word_boundary_with_ellipsis():
    text = "word " * 200
    out = truncate(text)
    assert len(out) <= 500
    assert out.endswith("word…")


def test_truncate_hard_cuts_one_long_word():
    out = truncate("x" * 600)
    assert len(out) == 500
    assert out.endswith("…")


def test_clean_username_accepts_valid_names():
    assert clean_username("@Some_User") == "some_user"


def test_clean_username_accepts_boundary_lengths():
    assert clean_username("abc") == "abc"
    assert clean_username("x" * 25) == "x" * 25


def test_clean_username_rejects_bad_names():
    assert clean_username("ab") is None
    assert clean_username("has space") is None
    assert clean_username("emoji😀") is None
    assert clean_username("x" * 26) is None


def test_format_duration():
    assert format_duration(45) == "45s"
    assert format_duration(12 * 60 + 5) == "12m"
    assert format_duration(3 * 3600 + 12 * 60) == "3h 12m"
    assert format_duration(-5) == "0s"


def test_strip_article():
    assert strip_article("The Eiffel Tower") == "Eiffel Tower"
    assert strip_article("an apple") == "apple"
    assert strip_article("a towel") == "towel"
    assert strip_article("  the  clock") == "clock"
    assert strip_article("theater") == "theater"  # only a whole leading word
    assert strip_article("A-ha") == "A-ha" and strip_article("A$AP Rocky") == "A$AP Rocky"  # not articles
    assert strip_article("the") == "the" and strip_article("") == ""


def test_fold_accents():
    assert fold_accents("Pokémon Mötley Crüe café") == "Pokemon Motley Crue cafe"


def test_typo_match():
    assert typo_match("jupitor", "jupiter")
    assert typo_match("pacman", "pac man")  # spaces don't matter
    assert typo_match("leonardo da vinsi", "leonardo da vinci")
    assert not typo_match("apollo 13", "apollo 11")  # numbers exact
    assert not typo_match("e minor", "a minor")  # short words exact
    assert not typo_match("louis xvi", "louis xiv")  # Roman numerals exact
    assert not typo_match("henry vii", "henry viii")
    assert not typo_match("1950s", "1940s")
    assert not typo_match("jupitor saturnn", "jupiter saturn")  # one typo in total
    assert not typo_match("cat", "car")  # too short for a typo
    assert not typo_match("wario", "mario")  # a typo never changes the first letter
    assert not typo_match("louis xvii", "louis xviii")  # a 5-letter Roman numeral is still exact
    assert not typo_match("1 38 billion", "13 8 billion")  # digit groups must match, not just digits
    assert typo_match("shaquile oneal", "shaquille o neal")  # split differently, still one typo


def test_within_one_edit():
    assert within_one_edit("jupiter", "jupiter")
    assert within_one_edit("jupiter", "jupitor")  # substitution
    assert within_one_edit("jupiter", "jupiterr")  # insertion
    assert within_one_edit("jupiter", "upiter")  # deletion
    assert within_one_edit("jupiter", "jupietr")  # neighbours swapped
    assert not within_one_edit("jupiter", "jpuietr")
    assert not within_one_edit("jupiter", "juxyter")  # two different letters side by side
    assert within_one_edit("", "a") and not within_one_edit("", "ab")
    assert not within_one_edit("abc", "cba")
    assert not within_one_edit("a", "abc")


def test_short_number():
    cases = {0: "0", 950: "950", 1000: "1K", 1234: "1.2K", 1150: "1.2K", 1350: "1.4K", 9950: "10K",
             10_500: "11K", 55_123: "55K", 241_000: "241K", 999_499: "999K", 999_500: "1M",
             1_234_567: "1.2M", 12_345_678: "12M", 1_500_000_000: "1.5B"}
    for n, text in cases.items():
        assert short_number(n) == text, n
    with pytest.raises(ValueError):
        short_number(-5)
