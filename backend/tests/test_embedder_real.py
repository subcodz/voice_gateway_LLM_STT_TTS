import os, pytest
pytest.importorskip("sentence_transformers")

def test_real_embedder_paraphrase(monkeypatch):
    monkeypatch.setenv("EMBEDDER", "real")
    from app.cache.semantic import SemanticCache, cosine_similarity
    sc = SemanticCache()
    a = sc.embed_text("what is bfs")
    b = sc.embed_text("what is the bfs algorithm")
    c = sc.embed_text("what are the office hours")
    assert cosine_similarity(a, b) > cosine_similarity(a, c)

