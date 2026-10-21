from app.validation.line_mapper import InlineComment, map_to_inline


def test_single_and_multi_line(sample_files):
    assert map_to_inline("app/users.py", 12, 12, sample_files) == InlineComment("app/users.py", 12)
    multi = map_to_inline("app/users.py", 10, 13, sample_files)
    assert (multi.start_line, multi.line) == (10, 13)
    api = multi.to_api("hi")
    assert api == {"path": "app/users.py", "body": "hi", "line": 13, "side": "RIGHT", "start_line": 10, "start_side": "RIGHT"}
    assert "start_line" not in InlineComment("p", 3).to_api("b")


def test_range_partly_outside_diff_falls_back_to_added_line(sample_files):
    c = map_to_inline("app/users.py", 1, 12, sample_files)
    assert c == InlineComment("app/users.py", 10)


def test_outside_diff_unknown_file_and_deleted(sample_files):
    assert map_to_inline("app/users.py", 100, 110, sample_files) is None
    assert map_to_inline("nope.py", 1, 1, sample_files) is None
    assert map_to_inline("app/users.py", 5, 4, sample_files) is None
