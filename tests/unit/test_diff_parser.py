from app.github.diff_parser import parse_diff
from tests.helpers import make_diff


def test_sample_diff(sample_files):
    assert set(sample_files) == {"app/users.py", "app/orders.py", "README.md"}
    users = sample_files["app/users.py"]
    assert users.added == set(range(10, 17)) and users.status == "modified"
    assert users.visible[12].text.startswith("    query = f")
    assert users.visible[12].kind == "add" and users.visible[9].kind == "context"
    assert 12 in users.changed_positions


def test_hunks_split_and_counts():
    old = "".join(f"line{i}\n" for i in range(1, 41))
    new = old.replace("line3\n", "LINE3\n").replace("line38\n", "LINE38\n")
    fd = parse_diff(make_diff("f.txt", old, new))["f.txt"]
    assert fd.hunks == 2 and fd.additions == 2 and fd.removals == 2
    assert fd.visible[3].kind == "add" and fd.visible[38].kind == "add"


def test_new_deleted_renamed_binary():
    new_file = parse_diff(make_diff("n.py", "", "a\nb\n"))["n.py"]
    assert new_file.status == "added" and new_file.added == {1, 2}
    deleted = parse_diff(
        "diff --git a/d.py b/d.py\ndeleted file mode 100644\n--- a/d.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-x\n-y\n"
    )["d.py"]
    assert deleted.status == "deleted" and deleted.removals == 2 and not deleted.visible
    ren = parse_diff("diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n")["new.py"]
    assert ren.status == "renamed" and ren.old_path == "old.py"
    binf = parse_diff("diff --git a/i.png b/i.png\nBinary files a/i.png and b/i.png differ\n")["i.png"]
    assert binf.binary


def test_removal_only_hunk_has_anchor():
    old = "a\nb\nc\nd\n"
    fd = parse_diff(make_diff("f.py", old, "a\nd\n", n=1))["f.py"]
    assert fd.removals == 2 and not fd.added
    assert fd.changed_positions  # anchors exist so findings about removals can be validated


def test_content_lines_that_look_like_headers_are_not_headers():
    diff = (
        "diff --git a/f.md b/f.md\n--- a/f.md\n+++ b/f.md\n@@ -1,2 +1,2 @@\n"
        "--- not a header\n+++ also not a header\n"
    )
    fd = parse_diff(diff)["f.md"]
    assert len(fd.lines) == 2 and fd.lines[0].kind == "remove" and fd.lines[1].kind == "add"


def test_no_newline_marker_and_empty_input():
    diff = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n\\ No newline at end of file\n"
    assert parse_diff(diff)["f"].additions == 1
    assert parse_diff("") == {}
    assert parse_diff("garbage\nnot a diff") == {}


def test_plain_unified_diff_without_git_header():
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1 +1,2 @@\n a\n+b\n--- a/y.py\n+++ b/y.py\n@@ -1 +1 @@\n-c\n+d\n"
    files = parse_diff(diff)
    assert set(files) == {"x.py", "y.py"} and files["x.py"].added == {2}
