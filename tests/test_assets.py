from bot.assets import Assets


def test_lines_skip_blank_and_comment_lines(assets: Assets):
    assert assets.words("animals") == ["alligator", "cat", "sea lion"]


def test_categories_are_sorted_file_stems(assets: Assets):
    assert assets.categories() == ["animals", "food"]


def test_lines_reads_top_level_files(assets: Assets):
    assert assets.lines("8ball") == ["Yes.", "No."]


def test_json_reads_top_level_json_files(assets: Assets):
    assert assets.json("riddles")[0]["answers"] == ["clock", "watch"]
