from memories.short_term import ShortTerm


def test_append_persists_to_disk(tmp_path):
    p = tmp_path / "st.json"
    mem = ShortTerm(str(p), max_entries=3)
    mem.append("user", "hello")
    mem.append("assistant", "hi")
    assert p.exists()
    assert len(mem.recent(10)) == 2


def test_recent_returns_last_n(tmp_path):
    mem = ShortTerm(str(tmp_path / "st.json"), max_entries=10)
    for i in range(5):
        mem.append("user", f"m{i}")
    recent = mem.recent(3)
    assert [m["content"] for m in recent] == ["m2", "m3", "m4"]


def test_buffer_caps_at_max_entries(tmp_path):
    mem = ShortTerm(str(tmp_path / "st.json"), max_entries=3)
    for i in range(5):
        mem.append("user", f"m{i}")
    assert len(mem.recent(10)) == 3
    assert mem.recent(10)[0]["content"] == "m2"


def test_clear_empties_buffer(tmp_path):
    p = tmp_path / "st.json"
    mem = ShortTerm(str(p), max_entries=5)
    mem.append("user", "x")
    mem.clear()
    assert mem.recent(10) == []


def test_loads_existing_file(tmp_path):
    p = tmp_path / "st.json"
    mem1 = ShortTerm(str(p), max_entries=5)
    mem1.append("user", "persisted")
    mem2 = ShortTerm(str(p), max_entries=5)
    assert len(mem2.recent(10)) == 1
    assert mem2.recent(10)[0]["content"] == "persisted"
