from bot.text import clean_username, format_duration, normalize, strip_invisible, truncate


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
