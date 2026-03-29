from dataclasses import dataclass


@dataclass
class SearchConfig:
    # Expansion
    expansion_enabled: bool = True
    expansion_max_sub_queries: int = 5

    # Retrieval
    entity_top_k: int = 20
    chunk_top_k: int = 20
    exact_min_term_length: int = 3

    # Entity boost
    entity_boost_top_n: int = 10
    entity_overlap_boost: float = 0.15
    specificity_threshold_ratio: float = 0.15

    # RRF
    rrf_k: int = 60
    max_results: int = 20

    # Embedding
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
