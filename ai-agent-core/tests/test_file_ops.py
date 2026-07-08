from skills.file_ops import FileOps


def test_read_returns_file_content(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello world")
    out = FileOps().execute({"op": "read", "path": str(p)})
    assert out["ok"] is True
    assert out["result"] == "hello world"
    assert out["error"] is None


def test_read_missing_file_returns_error(tmp_path):
    out = FileOps().execute({"op": "read", "path": str(tmp_path / "no.txt")})
    assert out["ok"] is False
    assert out["result"] is None
    assert "no such file" in out["error"].lower()


def test_clean_strips_whitespace_and_drops_blank_lines(tmp_path):
    p = tmp_path / "messy.txt"
    p.write_text("  foo  \n\nbar\n   \nbaz")
    out = FileOps().execute({"op": "clean", "path": str(p)})
    assert out["ok"] is True
    assert out["result"] == "foo\nbar\nbaz"


def test_unknown_op_returns_error():
    out = FileOps().execute({"op": "frobnicate", "path": "x"})
    assert out["ok"] is False
    assert "unknown op" in out["error"].lower()


def test_missing_path_returns_error():
    out = FileOps().execute({"op": "read"})
    assert out["ok"] is False
    assert "missing" in out["error"].lower()
