"""Tests for the legacy index_yaml_upsert (deprecated by Phase 2 GraphIndex).

保留旧测试以验证 backward-compat：index_yaml_upsert 函数仍然存在且可用，
但 process_file 已切换到 graph_index_upsert (SQLite)。
新代码应使用 graph_index_upsert / GraphIndex。
"""

import threading
from pathlib import Path

from scripts.pipeline_worker import index_yaml_upsert


def test_creates_tree_when_yaml_missing(tmp_path: Path):
    yaml_path = tmp_path / "index.yaml"
    added = index_yaml_upsert(yaml_path, "rag/corpus/a.md", "科技", "AI", "模型")
    assert added is True
    import yaml
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert data["tree"]["科技"]["AI"]["模型"][0]["path"] == "rag/corpus/a.md"
    assert data["tree"]["科技"]["AI"]["模型"][0]["level"] == "L4"


def test_idempotent_on_same_path(tmp_path: Path):
    yaml_path = tmp_path / "index.yaml"
    index_yaml_upsert(yaml_path, "rag/corpus/a.md", "科技", "AI", "模型")
    added = index_yaml_upsert(yaml_path, "rag/corpus/a.md", "科技", "AI", "模型")
    assert added is False
    import yaml
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    leaves = data["tree"]["科技"]["AI"]["模型"]
    assert len(leaves) == 1


def test_appends_distinct_paths_under_same_l3(tmp_path: Path):
    yaml_path = tmp_path / "index.yaml"
    index_yaml_upsert(yaml_path, "a.md", "科技", "AI", "模型")
    index_yaml_upsert(yaml_path, "b.md", "科技", "AI", "模型")
    import yaml
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    leaves = data["tree"]["科技"]["AI"]["模型"]
    assert [l["path"] for l in leaves] == ["a.md", "b.md"]


def test_separates_different_l3_branches(tmp_path: Path):
    yaml_path = tmp_path / "index.yaml"
    index_yaml_upsert(yaml_path, "a.md", "科技", "AI", "模型")
    index_yaml_upsert(yaml_path, "b.md", "职场", "成长", "策略")
    import yaml
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert "模型" in data["tree"]["科技"]["AI"]
    assert "策略" in data["tree"]["职场"]["成长"]
    assert "AI" not in data["tree"].get("职场", {})


def test_corrupt_yaml_backed_up_and_reset(tmp_path: Path):
    yaml_path = tmp_path / "index.yaml"
    yaml_path.write_text(": : not valid yaml : :", encoding="utf-8")
    added = index_yaml_upsert(yaml_path, "a.md", "科技", "AI", "模型")
    assert added is True
    backups = list(tmp_path.glob("index.yaml.bak.*"))
    assert len(backups) == 1
    import yaml
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert data["tree"]["科技"]["AI"]["模型"][0]["path"] == "a.md"


def test_concurrent_writes_do_not_lose_entries(tmp_path: Path):
    """旧路径仍 thread-safe（threading.Lock 保护）。新代码应走 GraphIndex (SQLite WAL)。"""
    yaml_path = tmp_path / "index.yaml"
    paths = [f"file_{i}.md" for i in range(20)]

    def worker(p: str) -> None:
        index_yaml_upsert(yaml_path, p, "科技", "AI", "模型")

    threads = [threading.Thread(target=worker, args=(p,)) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    import yaml
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    leaves = data["tree"]["科技"]["AI"]["模型"]
    got = {l["path"] for l in leaves}
    assert got == set(paths)
    assert len(leaves) == len(paths)
