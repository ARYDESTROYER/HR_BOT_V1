"""
Production-ready configuration settings for HR Bot
Optimized for low latency and cost efficiency
"""
import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # OpenAI Configuration
    openai_api_key: str = Field(default="", env="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", env="OPENAI_MODEL")  # Cost-optimized model
    temperature: float = Field(default=0.1, env="TEMPERATURE")  # Lower temp for consistency
    
    # Darwinbox API Configuration
    darwinbox_api_url: str = Field(default="", env="DARWINBOX_API_URL")
    darwinbox_api_key: str = Field(default="", env="DARWINBOX_API_KEY")
    darwinbox_tenant_id: str = Field(default="", env="DARWINBOX_TENANT_ID")
    darwinbox_timeout: int = Field(default=10, env="DARWINBOX_TIMEOUT")
    
    # Cache Configuration
    enable_cache: bool = Field(default=True, env="ENABLE_CACHE")
    cache_ttl: int = Field(default=3600, env="CACHE_TTL")  # 1 hour
    cache_dir: Path = Field(default=Path.home() / ".cache" / "hr_bot", env="CACHE_DIR")
    
    # RAG Configuration
    chunk_size: int = Field(default=800, env="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, env="CHUNK_OVERLAP")
    top_k_results: int = Field(default=12, env="TOP_K_RESULTS")  # Increased for larger document sets
    bm25_weight: float = Field(default=0.5, env="BM25_WEIGHT")
    vector_weight: float = Field(default=0.5, env="VECTOR_WEIGHT")
    
    # RRF Configuration for larger document sets
    rrf_multiplier: int = Field(default=12, env="RRF_CANDIDATE_MULTIPLIER")  # Increased from 8 to 12
    rrf_bm25_weight: float = Field(default=1.5, env="RRF_BM25_WEIGHT")
    rrf_vector_weight: float = Field(default=1.0, env="RRF_VECTOR_WEIGHT")
    
    # Embedding Configuration
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2", env="EMBEDDING_MODEL")  # Fast and efficient
    embedding_dimension: int = Field(default=384, env="EMBEDDING_DIMENSION")
    
    # Project Paths
    project_root: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent)
    data_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent / "data")
    vector_store_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent.parent / ".vector_store")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()

# Ensure directories exist
settings.cache_dir.mkdir(parents=True, exist_ok=True)
settings.vector_store_dir.mkdir(parents=True, exist_ok=True)
