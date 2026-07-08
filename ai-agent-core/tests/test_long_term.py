from memories.long_term import LongTerm


def test_add_and_query_by_subject(tmp_path):
    db = LongTerm(str(tmp_path / "lt.db"))
    db.add("user", "prefers", "dark_mode")
    db.add("user", "language", "python")
    rows = db.query(subject="user")
    assert len(rows) == 2
    assert ("user", "prefers", "dark_mode") in rows


def test_query_by_predicate(tmp_path):
    db = LongTerm(str(tmp_path / "lt.db"))
    db.add("alice", "knows", "bob")
    db.add("alice", "likes", "chocolate")
    db.add("bob", "knows", "carol")
    rows = db.query(predicate="knows")
    assert rows == [("alice", "knows", "bob"), ("bob", "knows", "carol")]


def test_query_no_match_returns_empty(tmp_path):
    db = LongTerm(str(tmp_path / "lt.db"))
    db.add("x", "y", "z")
    assert db.query(subject="nope") == []


def test_summarize_as_text_returns_concat(tmp_path):
    db = LongTerm(str(tmp_path / "lt.db"))
    db.add("user", "prefers", "dark_mode")
    db.add("user", "language", "python")
    text = db.summarize_as_text()
    assert "user prefers dark_mode" in text
    assert "user language python" in text


def test_persists_across_instances(tmp_path):
    p = str(tmp_path / "lt.db")
    db1 = LongTerm(p)
    db1.add("a", "b", "c")
    db2 = LongTerm(p)
    assert db2.query(subject="a") == [("a", "b", "c")]
