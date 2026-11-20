"""Схемы валидации данных Pydantic v2 для всех модулей REST API."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class GenreItem(BaseModel):
    id: int
    slug: str
    name_ru: str
    name_en: str
    dramas_count: Optional[int] = None


class PlatformItem(BaseModel):
    id: int
    slug: str
    name: str
    country: Optional[str] = "KR"
    platform_type: str = "TV"
    is_original: Optional[int] = None
    dramas_count: Optional[int] = None


class TropeBadge(BaseModel):
    id: int
    slug: str
    name_ru: str
    category: str
    weight: float
    source: str = "manual"


class TropeDictionaryItem(BaseModel):
    id: int
    slug: str
    name_ru: str
    name_en: str
    category: str
    description: str
    keywords: List[str] = Field(default_factory=list)
    base_weight: float
    dramas_count: int = 0
    avg_weight: float = 0.0


class CastMemberItem(BaseModel):
    id: int
    slug: str
    name_ru: str
    name_en: str
    name_kr: str = ""
    primary_profession: str
    photo_url: str = ""
    role_type: str
    character_name: str = ""
    billing_order: int = 10


class UserListMembership(BaseModel):
    slug: str
    name: str


class DramaSummary(BaseModel):
    id: int
    tmdb_id: Optional[int] = None
    slug: str
    title_ru: str
    title_en: str
    title_kr: str = ""
    title_romaja: str = ""
    synopsis_ru: str = ""
    release_year: int
    episodes_count: int
    episode_runtime: int = 60
    status: str
    rating: float
    votes_count: int = 0
    popularity_score: float = 0.0
    poster_url: str = ""
    age_rating: str = "16+"
    genres: List[GenreItem] = Field(default_factory=list)
    platforms: List[PlatformItem] = Field(default_factory=list)
    tropes: List[TropeBadge] = Field(default_factory=list)
    in_lists: List[UserListMembership] = Field(default_factory=list)


class DramaDetail(DramaSummary):
    synopsis_en: str = ""
    first_air_date: str = ""
    backdrop_url: str = ""
    created_at: str = ""
    updated_at: str = ""
    cast: List[CastMemberItem] = Field(default_factory=list)
    user_entries: List[Dict[str, Any]] = Field(default_factory=list)


class DramaListResponse(BaseModel):
    items: List[DramaSummary]
    total: int
    limit: int
    offset: int


class DramaCreateRequest(BaseModel):
    title_ru: str = Field(..., min_length=1, max_length=200)
    title_en: str = Field(..., min_length=1, max_length=200)
    title_kr: str = ""
    title_romaja: str = ""
    synopsis_ru: str = ""
    release_year: int = Field(..., ge=1980, le=2035)
    episodes_count: int = Field(default=16, ge=1, le=200)
    status: Literal["Ongoing", "Completed", "Upcoming", "Cancelled"] = "Completed"
    rating: float = Field(default=8.0, ge=0.0, le=10.0)
    poster_url: str = ""
    genre_slugs: List[str] = Field(default_factory=list)
    trope_slugs: List[str] = Field(default_factory=list)


class SearchHit(BaseModel):
    drama: DramaSummary
    score: float
    match_field: str
    matched_text: str


class FuzzySearchResponse(BaseModel):
    raw_query: str
    effective_query: str
    corrected_query: Optional[str] = None
    correction_kind: Literal["none", "exact", "typo", "layout", "layout_and_typo"] = "none"
    was_corrected: bool = False
    banner_message: Optional[str] = None
    latency_ms: float
    total: int
    results: List[SearchHit]


class AutocompleteItem(BaseModel):
    entity_type: Literal["drama", "person", "trope"]
    id: int
    slug: str
    label: str
    sublabel: str = ""
    score: float


class AutocompleteResponse(BaseModel):
    raw_query: str
    converted_query: Optional[str] = None
    correction_hint: Optional[str] = None
    latency_ms: float
    items: List[AutocompleteItem]


class RecommendationExplanation(BaseModel):
    shared_tropes: List[str] = Field(default_factory=list)
    shared_genres: List[str] = Field(default_factory=list)
    shared_persons: List[str] = Field(default_factory=list)
    trope_similarity: float
    genre_similarity: float
    cast_similarity: float


class RecommendationItem(BaseModel):
    drama: DramaSummary
    similarity_score: float
    match_percent: int
    explanation: RecommendationExplanation


class RecommendationsResponse(BaseModel):
    source_drama_id: int
    source_title: str
    recommendations: List[RecommendationItem]


class GraphNode(BaseModel):
    id: str
    entity_id: int
    entity_type: Literal["drama", "person", "trope", "genre"]
    label: str
    sublabel: str = ""
    weight: float = 1.0
    is_center: bool = False


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    weight: float = 1.0


class KnowledgeGraphResponse(BaseModel):
    center_node_id: str
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    stats: Dict[str, int]


class UserListCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=250)


class UserListItemUpsertRequest(BaseModel):
    drama_id: int
    personal_rating: Optional[float] = Field(default=None, ge=1.0, le=10.0)
    watched_episodes: int = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=500)


class SyncTriggerRequest(BaseModel):
    mode: Literal["auto", "tmdb", "offline"] = "auto"


class SyncStatusResponse(BaseModel):
    is_running: bool
    scheduler_active: bool
    interval_hours: int
    next_run_at: Optional[str] = None
    has_tmdb_key: bool
    recent_logs: List[Dict[str, Any]] = Field(default_factory=list)


class SearchBenchmarkCaseResult(BaseModel):
    query: str
    expected_slug: str
    actual_top_slug: Optional[str]
    actual_top_title: Optional[str]
    case_type: str
    correction_kind: str
    score: float
    latency_ms: float
    passed: bool


class RecommendationBenchmarkCaseResult(BaseModel):
    source_slug: str
    source_title: str
    predicted_slugs: List[str]
    relevant_slugs: List[str]
    precision_at_5: float
    recall_at_5: float
    ndcg_at_5: float


class BenchmarkSuiteResponse(BaseModel):
    search_summary: Dict[str, Any]
    search_cases: List[SearchBenchmarkCaseResult]
    recommendation_summary: Dict[str, Any]
    recommendation_cases: List[RecommendationBenchmarkCaseResult]
