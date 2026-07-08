from harness.cache_guard import CacheGuard


def test_miss_returns_none(tmp_path):
    cache = CacheGuard(str(tmp_path / "c.db"))
    assert cache.get("hello") is None


def test_set_then_get_returns_result(tmp_path):
    cache = CacheGuard(str(tmp_path / "c.db"))
    cache.set("hello world", {"answer": 42})
    out = cache.get("hello world")
    assert out == {"answer": 42}


def test_normalization_collapses_whitespace_and_case(tmp_path):
    cache = CacheGuard(str(tmp_path / "c.db"))
    cache.set("  Hello   WORLD  ", {"x": 1})
    assert cache.get("hello world") == {"x": 1}


def test_expiry_returns_none(tmp_path):
    cache = CacheGuard(str(tmp_path / "c.db"), ttl_seconds=0)
    cache.set("q", {"a": 1})
    # ttl=0 means immediate expiry
    import time
    time.sleep(0.01)
    assert cache.get("q") is None


def test_clear_empties_cache(tmp_path):
    cache = CacheGuard(str(tmp_path / "c.db"))
    cache.set("q", {"a": 1})
    cache.clear()
    assert cache.get("q") is None


def test_persists_across_instances(tmp_path):
    p = str(tmp_path / "c.db")
    c1 = CacheGuard(p)
    c1.set("q", {"a": 1})
    c2 = CacheGuard(p)
    assert c2.get("q") == {"a": 1}
