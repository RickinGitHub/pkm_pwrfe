import os

from agent import AgentCore


def build_agent() -> AgentCore:
    agent = AgentCore(
        rules_path=os.environ.get("RULES_CONFIG", "config/rules.yaml"),
        routing_path=os.environ.get("ROUTING_CONFIG", "config/routing.yaml"),
        cache_path=os.environ.get("CACHE_PATH", "memories/cache.db"),
        short_term_path=os.environ.get("SHORT_TERM_PATH", "memories/short_term.json"),
        long_term_path=os.environ.get("LONG_TERM_DB_PATH", "memories/long_term.db"),
    )

    from skills.file_ops import FileOps
    from skills.math_logic import MathLogic
    from skills.fetch_web_to_md import FetchWebToMd
    from skills.context import ContextSkill
    from skills.reflect import ReflectSkill
    from skills.review import ReviewSkill
    from skills.find_ops import FindOps
    from skills.grep_ops import GrepOps
    from skills.tree_ops import TreeOps
    from skills.pipeline_ops import PipelineOps
    from skills.react import ReactSkill
    from mcp.servers.knowledge_server import KnowledgeServer
    from mcp.servers.hybrid_knowledge_server import HybridKnowledgeServer
    from mcp.servers.file_search_server import FileSearchServer
    from rag.corpus_loader import CorpusLoader
    from rag.metadata import MetadataIndex
    from rag.embedder import get_embedder
    from rag.fts_index import FtsIndex
    from memories.url_registry import UrlRegistry

    chunk_enabled = os.environ.get("CORPUS_CHUNK_ENABLED", "1").lower() in ("1", "true", "yes")
    chunk_size = int(os.environ.get("CORPUS_CHUNK_SIZE", "1200"))
    chunk_overlap = int(os.environ.get("CORPUS_CHUNK_OVERLAP", "150"))

    corpus_loader = CorpusLoader("rag/corpus", chunk=False)
    corpus_loader_chunked = CorpusLoader(
        "rag/corpus", chunk=chunk_enabled,
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
    ) if chunk_enabled else corpus_loader

    metadata = MetadataIndex("rag/corpus")
    metadata.build()

    embedder = get_embedder()

    fts_path = os.environ.get("FTS_INDEX_PATH", "rag/fts_index.db")
    fts_index = FtsIndex(fts_path)

    agent.register_skill("math_logic", MathLogic())
    agent.register_skill("file_ops", FileOps())
    url_registry = UrlRegistry(os.environ.get("URL_REGISTRY_PATH", "memories/url_map.db"))
    agent.register_skill("fetch_web", FetchWebToMd(url_registry=url_registry))
    agent.register_skill("context", ContextSkill())
    agent.register_skill("reflect", ReflectSkill())
    agent.register_skill("review", ReviewSkill())
    agent.register_skill("find_ops", FindOps())
    agent.register_skill("grep_ops", GrepOps())
    agent.register_skill("tree_ops", TreeOps())
    agent.register_skill("pipeline_ops", PipelineOps())
    agent.register_skill("react", ReactSkill(agent=agent))

    agent.register_mcp(
        "knowledge",
        KnowledgeServer(corpus_loader, metadata=metadata, fts_index=fts_index, graph_db_path="rag/graph_index.db"),
    )
    agent.register_mcp(
        "hybrid_knowledge",
        HybridKnowledgeServer(corpus_loader_chunked, embedder=embedder),
    )
    agent.register_mcp("file_search", FileSearchServer())

    agent.bootstrap_memory()
    return agent
