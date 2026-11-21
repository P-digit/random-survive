"""생존 지식 검색 (RAG 파트).

data/survival_guide.txt → Chunking → Embedding → ChromaDB 저장 → 질문과 비슷한 Chunk 검색.
chromadb가 설치되어 있지 않으면 같은 임베딩을 numpy로 직접 비교해서 검색한다(코사인 유사도).
임베딩 자체가 실패하면 간단한 키워드 검색으로 대신한다.
"""
import json
import re

import numpy as np

from .config import CHROMA_DIR, DATA_DIR, EMBEDDING_MODEL, MODEL_DIR

GUIDE_PATH = DATA_DIR / "survival_guide.txt"
COLLECTION_NAME = "survival_guide"

_chunks = None
_collection = None
_vector_failed = False
_matrix = None


def _model_slug():
    return re.sub(r"[^A-Za-z0-9_-]", "_", EMBEDDING_MODEL)


def embed_cache_path():
    """임베딩 캐시 파일. 모델마다 따로 둬서 공급자를 바꿔도 서로 덮어쓰지 않는다."""
    return MODEL_DIR / f"guide_embeddings_{_model_slug()}.json"


def collection_name():
    """임베딩 모델마다 컬렉션을 따로 둔다 (모델이 다르면 벡터를 섞어 비교할 수 없다)."""
    return f"{COLLECTION_NAME}_{_model_slug()}"[:63]


def load_chunks():
    """문서를 주제(빈 줄) 단위 Chunk로 나눈다. 각 Chunk는 '[제목]\\n본문' 형태다."""
    global _chunks
    if _chunks is None:
        text = GUIDE_PATH.read_text(encoding="utf-8")
        _chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
    return _chunks


def embed(client, texts):
    response = client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
    return [d.embedding for d in response.data]


def get_collection(client):
    """ChromaDB 컬렉션을 준비한다. 비어 있으면 문서를 임베딩해서 저장한다."""
    global _collection
    if _collection is None:
        import chromadb
        chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = chroma.get_or_create_collection(name=collection_name())
        chunks = load_chunks()
        if collection.count() != len(chunks):
            if collection.count() > 0:      # 문서가 바뀌었으면 다시 만든다
                chroma.delete_collection(collection_name())
                collection = chroma.get_or_create_collection(name=collection_name())
            collection.add(
                ids=[f"chunk{i}" for i in range(len(chunks))],
                documents=chunks,
                embeddings=embed(client, chunks),
            )
        _collection = collection
    return _collection


def numpy_search(client, query, n_results=3):
    """ChromaDB 없이 하는 벡터 검색: Chunk 임베딩을 파일에 저장해 두고 코사인 유사도로 비교한다."""
    global _matrix
    chunks = load_chunks()
    if _matrix is None:
        try:
            cached = json.loads(embed_cache_path().read_text(encoding="utf-8"))
            assert cached["chunks"] == chunks       # 문서가 바뀌었으면 다시 만든다
            assert cached.get("model") == EMBEDDING_MODEL   # 임베딩 모델이 바뀌면 벡터 공간이 달라 다시 만든다
            vectors = cached["embeddings"]
        except Exception:
            vectors = embed(client, chunks)
            MODEL_DIR.mkdir(exist_ok=True)
            embed_cache_path().write_text(json.dumps({"model": EMBEDDING_MODEL, "chunks": chunks,
                                                "embeddings": vectors}), encoding="utf-8")
        matrix = np.array(vectors, dtype=float)
        _matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    q = np.array(embed(client, [query])[0], dtype=float)
    scores = _matrix @ (q / np.linalg.norm(q))
    return [chunks[i] for i in np.argsort(-scores)[:n_results]]


def keyword_search(query, n_results=3):
    """벡터 검색을 못 쓸 때의 예비 검색: 질문의 글자 2-gram이 많이 겹치는 Chunk를 고른다."""
    grams = {query[i:i + 2] for i in range(len(query) - 1) if query[i:i + 2].strip()}
    scored = sorted(load_chunks(), key=lambda c: -sum(g in c for g in grams))
    return scored[:n_results]


def search(client, query, n_results=3):
    """질문과 관련된 생존 지식 Chunk를 반환한다."""
    global _vector_failed
    if client is not None and not _vector_failed:
        try:
            try:
                import chromadb  # noqa: F401
            except ImportError:
                return numpy_search(client, query, n_results)
            collection = get_collection(client)
            result = collection.query(query_embeddings=embed(client, [query]), n_results=n_results)
            return result["documents"][0]
        except Exception as e:
            _vector_failed = True
            print(f"[RAG] 벡터 검색을 사용할 수 없어 키워드 검색으로 전환합니다: {e}")
    return keyword_search(query, n_results)
