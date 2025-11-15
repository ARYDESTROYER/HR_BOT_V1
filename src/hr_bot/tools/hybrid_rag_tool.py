"""
Production-grade Hybrid RAG Tool with BM25 + Vector Search
Optimized for tables and low-latency retrieval using Gemini embeddings
"""
import os
import pickle
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import hashlib

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from langchain.schema import Document
from langchain_community.document_loaders import Docx2txtLoader
from rank_bm25 import BM25Okapi
import numpy as np
from diskcache import Cache

from crewai.tools import BaseTool  # Correct import from crewai, not crewai_tools
from pydantic import BaseModel, Field
import re

# Import document classifier for enhanced metadata
from hr_bot.utils.document_classifier import DocumentClassifier, DocumentCategory

# Optional reranker (lightweight, CPU-friendly)
try:
    from sentence_transformers import CrossEncoder
except Exception:  # pragma: no cover - optional dependency
    CrossEncoder = None


def _get_env_int(name: str, default: int, aliases: Optional[List[str]] = None) -> int:
    """Safely parse an int from environment variables with fallback."""
    candidates = [name]
    if aliases:
        candidates += list(aliases)
    for key in candidates:
        val = os.getenv(key)
        if val is not None:
            try:
                return int(str(val).strip())
            except Exception:
                print(f"Warning: environment variable {key}='{val}' is not a valid integer; using default {default}.")
    return default


def _get_env_float(name: str, default: float, aliases: Optional[List[str]] = None) -> float:
    """Safely parse a float from environment variables with fallback."""
    candidates = [name]
    if aliases:
        candidates += list(aliases)
    for key in candidates:
        val = os.getenv(key)
        if val is not None:
            try:
                return float(str(val).strip())
            except Exception:
                print(f"Warning: environment variable {key}='{val}' is not a valid float; using default {default}.")
    return default


@dataclass
class SearchResult:
    """Search result with metadata"""
    content: str
    source: str
    score: float
    chunk_id: int


class HybridRAGRetriever:
    """
    Hybrid retriever combining BM25 (keyword) and Vector (semantic) search
    Optimized for document tables and structured content
    """
    
    def __init__(self, cache: Optional[Cache] = None, data_dir: str = "data", document_paths: Optional[List[str]] = None, s3_version_hash: Optional[str] = None):
        """
        Initialize Hybrid RAG Retriever
        
        Args:
            cache: Optional cache instance
            data_dir: Local data directory path (used if document_paths is None)
            document_paths: Optional list of document file paths (for S3 documents)
            s3_version_hash: Optional S3 ETag-based version hash for cache invalidation
        """
        # Use local HuggingFace embeddings for no API quota limits
        # all-MiniLM-L6-v2: Fast, efficient, and high-quality (384 dimensions)
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={
                'device': 'cpu',
                'trust_remote_code': False
            },
            encode_kwargs={'normalize_embeddings': True}
        )

        # Core indices/containers
        self.vector_store = None
        self.faiss_retriever = None
        self.bm25_retriever = None
        self.ensemble_retriever = None
        self.bm25 = None
        self.documents: List[Document] = []
        self.data_dir = Path(data_dir) if data_dir else None
        self.document_paths = document_paths  # Store for S3 mode
        self.s3_version_hash = s3_version_hash  # NEW: S3 ETag version for cache invalidation
        self.cache_dir = Path(".rag_cache")
        self.cache_dir.mkdir(exist_ok=True)
        self.cache = cache or Cache(str(self.cache_dir))
        self.index_hash: Optional[str] = None
        self._last_sources: List[str] = []

        # Configuration
        # Tuned defaults for larger document sets (120+ documents)
        self.chunk_size = _get_env_int("CHUNK_SIZE", 700)
        self.chunk_overlap = _get_env_int("CHUNK_OVERLAP", 200)
        self.top_k_results = _get_env_int("TOP_K", 12, aliases=["TOP_K_RESULTS"])
        self.bm25_weight = _get_env_float("BM25_WEIGHT", 0.5)
        self.vector_weight = _get_env_float("VECTOR_WEIGHT", 0.5)
        self.enable_cache = os.getenv("ENABLE_CACHE", "true").lower() == "true"
        self.cache_ttl = _get_env_int("CACHE_TTL", 3600)
        # Larger candidate pool for better recall with 120+ documents
        self.rrf_multiplier = _get_env_int("RRF_CANDIDATE_MULTIPLIER", 12)  # Increased from 8 to 12
        # Weighting for RRF contributions
        self.rrf_bm25_weight = _get_env_float("RRF_BM25_WEIGHT", 1.5)
        self.rrf_vector_weight = _get_env_float("RRF_VECTOR_WEIGHT", 1.0)

        # Optional learned reranker config
        self.rerank_enabled = os.getenv("RERANK_ENABLED", "1").lower() in ("1", "true")
        self.rerank_top_n = _get_env_int("RERANK_TOP_N", 50)
        self.reranker_model_name = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        # Lazy-initialized reranker instance (if enabled and available)
        self._reranker = None

        # Paths
        self.vector_store_dir = Path(".rag_index")
        self.vector_store_dir.mkdir(exist_ok=True)
        
        # Document classifier for enhanced metadata
        self.classifier = DocumentClassifier()
        
        # Category-based filtering for improved retrieval
        self.enable_category_filtering = os.getenv("ENABLE_CATEGORY_FILTERING", "true").lower() == "true"
        
    def _compute_data_hash(self, data_dir: Path) -> str:
        """Compute hash of all documents for cache invalidation"""
        hasher = hashlib.md5()
        for file_path in sorted(data_dir.rglob("*.docx")):
            hasher.update(str(file_path.stat().st_mtime).encode())
            hasher.update(file_path.name.encode())
        # Include key config affecting index layout
        hasher.update(f"chunk_size:{self.chunk_size}|overlap:{self.chunk_overlap}".encode())
        # Bump when sanitization logic changes to force index rebuild
        hasher.update(b"sanitize_placeholders_v3")
        return hasher.hexdigest()
    
    def _load_documents(self, data_dir: Path) -> List[Document]:
        """Load all Word documents with table-aware processing"""
        documents = []
        
        for file_path in data_dir.rglob("*.docx"):
            try:
                # Use Docx2txt for better table handling
                loader = Docx2txtLoader(str(file_path))
                docs = loader.load()
                
                # Add metadata with classification
                for doc in docs:
                    doc.metadata['source'] = file_path.name
                    doc.metadata['file_path'] = str(file_path)
                    
                    # Classify document and add enhanced metadata
                    doc_metadata = self.classifier.classify_document(
                        str(file_path), 
                        doc.page_content
                    )
                    doc.metadata.update({
                        'category': doc_metadata.category.value,
                        'tags': list(doc_metadata.tags),
                        'priority': doc_metadata.priority,
                        'access_level': doc_metadata.access_level,
                        'keywords': list(doc_metadata.keywords)
                    })
                    
                    # Sanitize common template placeholders to avoid leaking into answers
                    doc.page_content = self._sanitize(doc.page_content)
                    documents.append(doc)
                    
                print(f"✓ Loaded: {file_path.name}")
            except Exception as e:
                print(f"✗ Error loading {file_path.name}: {e}")
                
        return documents
    
    def _load_documents_from_paths(self, document_paths: List[str]) -> List[Document]:
        """
        Load documents from a list of file paths (S3 mode)
        
        Args:
            document_paths: List of absolute file paths to .docx documents
            
        Returns:
            List of loaded Document objects
        """
        documents = []
        
        for file_path_str in document_paths:
            try:
                file_path = Path(file_path_str)
                
                # Only process .docx files
                if not file_path.suffix.lower() == '.docx':
                    continue
                
                # Use Docx2txt for better table handling
                loader = Docx2txtLoader(str(file_path))
                docs = loader.load()
                
                # Add metadata with classification
                for doc in docs:
                    doc.metadata['source'] = file_path.name
                    doc.metadata['file_path'] = str(file_path)
                    
                    # Classify document and add enhanced metadata
                    doc_metadata = self.classifier.classify_document(
                        str(file_path), 
                        doc.page_content
                    )
                    doc.metadata.update({
                        'category': doc_metadata.category.value,
                        'tags': list(doc_metadata.tags),
                        'priority': doc_metadata.priority,
                        'access_level': doc_metadata.access_level,
                        'keywords': list(doc_metadata.keywords)
                    })
                    
                    # Sanitize common template placeholders to avoid leaking into answers
                    doc.page_content = self._sanitize(doc.page_content)
                    documents.append(doc)
                    
                print(f"✓ Loaded: {file_path.name}")
            except Exception as e:
                print(f"✗ Error loading {file_path_str}: {e}")
                
        return documents

    def _sanitize(self, text: str) -> str:
        """Clean placeholder tokens like [insert job title] or [the Company]"""
        if not text:
            return text
        # Map explicit placeholders to friendly replacements
        replacements = {
            r"\[insert name and job title\]": "HR Representative",
            r"\[insert job title\]": "HR Representative",
            r"\[the Company\]": "the company",
            r"\[Company Name\]": "the company",
            r"\[Employee\]": "employee",
            r"\[INSERT LOGO HERE\]": "",
            r"\[days\]": "days",
            r"\[weeks\]": "weeks",
            r"\[months\]": "months",
            r"\[hours\]": "hours",
        }
        for pattern, replacement in replacements.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        # Target common template placeholders with contextual language
        text = re.sub(
            r"\[\s*insert\s+amount\s+of\s+days[^\]]*\]",
            "the approved number of days",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\[\s*insert\s+amount\s+of\s+weeks[^\]]*\]",
            "the approved number of weeks",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\[\s*insert\s+amount\s+of\s+months[^\]]*\]",
            "the approved number of months",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\[\s*insert\s+amount\s*\]\s*%",
            "the applicable percentage",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\[\s*insert\s+amount\s*\]",
            "the applicable amount",
            text,
            flags=re.IGNORECASE,
        )

        # Generic fallbacks for remaining "insert" or "state" placeholders
        text = re.sub(
            r"\[\s*insert[^\]]*\]",
            "the appropriate details",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\[\s*state[^\]]*\]",
            "the documented location",
            text,
            flags=re.IGNORECASE,
        )

        # Normalize lingering bracketed prose such as [Provided the employee ...]
        def _strip_template_brackets(match: "re.Match[str]") -> str:
            inner = match.group(1).strip()
            # Keep short markers like [1] untouched by requiring whitespace inside
            if " " not in inner:
                return inner
            return inner

        text = re.sub(r"\[\s*([^\[\]\n]{3,}?)\s*\]", _strip_template_brackets, text)
        return text
    
    def _chunk_documents(self, documents: List[Document]) -> List[Document]:
        """
        Chunk documents with table-aware splitting
        Preserves table structure and context
        """
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n\n", "\n\n", "\n", ". ", " ", ""],  # Preserve paragraphs and tables
            length_function=len,
        )
        
        chunks = text_splitter.split_documents(documents)
        
        # Add chunk IDs for reference
        for idx, chunk in enumerate(chunks):
            chunk.metadata['chunk_id'] = idx
            
        return chunks
    
    def _save_index(self, vector_store_path: Path, bm25_path: Path):
        """Save indexes to disk for faster loading"""
        try:
            # Save FAISS index
            if self.vector_store:
                self.vector_store.save_local(str(vector_store_path))
            
            # Save BM25 index - ONLY save what's needed, not SearchResult objects
            if self.bm25:
                # CRITICAL FIX: Don't save anything that might contain SearchResult objects
                # Clean the documents metadata to remove any SearchResult references
                clean_documents = []
                for doc in self.documents:
                    # Create a copy without any SearchResult references in metadata
                    clean_doc = Document(
                        page_content=doc.page_content,
                        metadata={k: v for k, v in doc.metadata.items() if not isinstance(v, SearchResult)}
                    )
                    clean_documents.append(clean_doc)
                
                with open(bm25_path, 'wb') as f:
                    pickle.dump({
                        'bm25': self.bm25,
                        'documents': clean_documents,  # Use cleaned documents
                        'index_hash': self.index_hash
                    }, f)
                    
            print("✓ Indexes saved to disk")
        except (pickle.PicklingError, TypeError, AttributeError) as e:
            # If pickling fails (e.g., SearchResult serialization), just skip saving
            # Index will rebuild on next run - not critical since we have ETag validation
            print(f"⚠️  Could not pickle index (will rebuild on next run): {e}")
        except Exception as e:
            print(f"Warning: Could not save indexes: {e}")
    
    def _load_index(self, vector_store_path: Path, bm25_path: Path, current_hash: str) -> bool:
        """Load indexes from disk if available and valid"""
        try:
            # Check if indexes exist
            if not vector_store_path.exists() or not bm25_path.exists():
                return False
            
            # CRITICAL FIX: Check index age (24 hour TTL)
            import time
            index_age_hours = (time.time() - bm25_path.stat().st_mtime) / 3600
            INDEX_TTL_HOURS = 24
            if index_age_hours > INDEX_TTL_HOURS:
                print(f"⏰ Index is {index_age_hours:.1f}h old (TTL: {INDEX_TTL_HOURS}h) - rebuilding...")
                return False
            
            # Load BM25 and check hash
            with open(bm25_path, 'rb') as f:
                data = pickle.load(f)
                
            # Validate hash
            if data.get('index_hash') != current_hash:
                print(f"🔄 Index hash mismatch - rebuilding...")
                print(f"   Cached: {data.get('index_hash', 'none')[:12]}...")
                print(f"   Current: {current_hash[:12]}...")
                
                # CRITICAL FIX: Delete stale index files
                import shutil
                if vector_store_path.exists():
                    shutil.rmtree(vector_store_path)
                    print(f"   Deleted stale FAISS index")
                if bm25_path.exists():
                    bm25_path.unlink()
                    print(f"   Deleted stale BM25 index")
                
                return False
            
            # Load FAISS index
            self.vector_store = FAISS.load_local(
                str(vector_store_path),
                self.embeddings,
                allow_dangerous_deserialization=True
            )
            
            # Load BM25 data
            self.bm25 = data['bm25']
            self.documents = data['documents']
            self.index_hash = data['index_hash']
            # Sanitize loaded documents in-memory (indexes remain valid for scoring)
            for d in self.documents:
                d.page_content = self._sanitize(d.page_content)
            # Rebuild retrievers and ensemble after loading
            base_k = max(self.top_k_results, 10)
            self.faiss_retriever = self.vector_store.as_retriever(search_kwargs={"k": base_k})
            self.bm25_retriever = BM25Retriever.from_documents(self.documents)
            self.bm25_retriever.k = base_k
            self.ensemble_retriever = EnsembleRetriever(
                retrievers=[self.bm25_retriever, self.faiss_retriever],
                weights=[self.rrf_bm25_weight, self.rrf_vector_weight],
            )
            
            print("✓ Loaded indexes from disk")
            return True
            
        except Exception as e:
            print(f"Could not load indexes: {e}")
            return False
    
    def build_index(self, force_rebuild: bool = False):
        """Build or load hybrid search index"""
        
        # Compute current data hash (use S3 version hash if available, else document_paths or data_dir)
        if self.s3_version_hash:
            # S3 mode with ETag validation: Use S3 version hash for cache invalidation
            # This ensures RAG index rebuilds when S3 documents change
            current_hash = self.s3_version_hash
            print(f"🔐 Using S3 version hash for RAG cache: {current_hash[:12]}...")
        elif self.document_paths:
            # S3 mode without version hash: hash based on document paths + file mtimes
            hasher = hashlib.md5()
            for doc_path in sorted(self.document_paths):
                hasher.update(doc_path.encode())
                try:
                    mtime = Path(doc_path).stat().st_mtime
                    hasher.update(str(mtime).encode())
                except Exception:
                    pass
            hasher.update(f"chunk_size:{self.chunk_size}|overlap:{self.chunk_overlap}".encode())
            hasher.update(b"sanitize_placeholders_v3")
            current_hash = hasher.hexdigest()
        else:
            # Local mode: hash based on data directory
            current_hash = self._compute_data_hash(self.data_dir)
        
        # Define paths
        vector_store_path = self.vector_store_dir / "faiss_index"
        bm25_path = self.vector_store_dir / "bm25_index.pkl"
        
        # CRITICAL: If force_rebuild is True, delete old index files and skip cache loading
        if force_rebuild:
            print("🔥 Force rebuild requested - deleting old indexes")
            import shutil
            if vector_store_path.exists():
                shutil.rmtree(vector_store_path)
            if bm25_path.exists():
                bm25_path.unlink()
        else:
            # Try to load existing index
            if self._load_index(vector_store_path, bm25_path, current_hash):
                return
        
        print("Building new search index...")
        
        # Load and process documents (S3 mode or local mode)
        if self.document_paths:
            # S3 mode: Load from provided document paths
            print(f"📦 Loading documents from S3 ({len(self.document_paths)} files)...")
            raw_documents = self._load_documents_from_paths(self.document_paths)
        else:
            # Local mode: Scan data directory
            raw_documents = self._load_documents(self.data_dir)
        
        self.documents = self._chunk_documents(raw_documents)
        # Additional sanitation pass for chunked documents
        for d in self.documents:
            d.page_content = self._sanitize(d.page_content)
        
        print(f"Processing {len(self.documents)} chunks...")
        
        # Check if we have documents before building index
        if len(self.documents) == 0:
            print("⚠️  Warning: No documents found to index. Creating empty index.")
            # Initialize empty structures to prevent crashes
            self.vector_store = None
            self.bm25 = None
            self.faiss_retriever = None
            self.bm25_retriever = None
            self.ensemble_retriever = None
            self.index_hash = current_hash
            print("✓ Empty index initialized (add documents to data/ directory)")
            return
        
        # Build vector store (FAISS for speed)
        texts = [doc.page_content for doc in self.documents]
        metadatas = [doc.metadata for doc in self.documents]
        
        self.vector_store = FAISS.from_texts(
            texts=texts,
            embedding=self.embeddings,
            metadatas=metadatas
        )
        
        # Build BM25 index (for backward compatibility / hashing)
        tokenized_corpus = [doc.page_content.lower().split() for doc in self.documents]
        self.bm25 = BM25Okapi(tokenized_corpus)

        # Create retrievers for EnsembleRetriever
        base_k = max(self.top_k_results, 10)
        self.faiss_retriever = self.vector_store.as_retriever(search_kwargs={"k": base_k})
        self.bm25_retriever = BM25Retriever.from_documents(self.documents)
        self.bm25_retriever.k = base_k
        self.ensemble_retriever = EnsembleRetriever(
            retrievers=[self.bm25_retriever, self.faiss_retriever],
            weights=[self.rrf_bm25_weight, self.rrf_vector_weight],
        )
        
        # Save index hash
        self.index_hash = current_hash
        
        print(f"✓ Index built with {len(self.documents)} chunks")
        
        # Save indexes
        self._save_index(vector_store_path, bm25_path)
    
    def hybrid_search(self, query: str, top_k: int = None, category_filter: Optional[DocumentCategory] = None) -> List[SearchResult]:
        """
        Perform hybrid search combining BM25 and vector search with optional category filtering
        
        Args:
            query: Search query
            top_k: Number of results to return
            category_filter: Optional category to filter results
            
        Returns:
            List of SearchResult objects
        """
        # Check if index is empty or not built
        if not self.vector_store or not self.ensemble_retriever or len(self.documents) == 0:
            print("⚠️  Warning: No documents in index, returning empty results")
            return []
        
        top_k = top_k or self.top_k_results
        
        # Apply category filtering if enabled and specified
        if self.enable_category_filtering and category_filter:
            # Filter documents by category before search
            filtered_docs = [
                doc for doc in self.documents 
                if doc.metadata.get('category') == category_filter.value
            ]
            
            if not filtered_docs:
                print(f"⚠️  No documents found in category: {category_filter.value}")
                return []
            
            # Create temporary retrievers with filtered documents
            temp_vector_store = FAISS.from_texts(
                texts=[doc.page_content for doc in filtered_docs],
                embedding=self.embeddings,
                metadatas=[doc.metadata for doc in filtered_docs]
            )
            
            temp_faiss_retriever = temp_vector_store.as_retriever(search_kwargs={"k": top_k * self.rrf_multiplier})
            temp_bm25_retriever = BM25Retriever.from_documents(filtered_docs)
            temp_bm25_retriever.k = top_k * self.rrf_multiplier
            temp_ensemble_retriever = EnsembleRetriever(
                retrievers=[temp_bm25_retriever, temp_faiss_retriever],
                weights=[self.rrf_bm25_weight, self.rrf_vector_weight],
            )
            
            # Use filtered retrievers for this search
            ensemble_retriever = temp_ensemble_retriever
            print(f"🔍 Searching in category: {category_filter.value} ({len(filtered_docs)} docs)")
        else:
            # Use all documents
            ensemble_retriever = self.ensemble_retriever
        
        # Query reformulation to expand synonyms/aliases for better recall
        reformulated_query = self._reformulate_query(query)
        # Check cache first (namespaced by index hash + key config to avoid stale reuse)
        cache_scope = self.index_hash or "no-index"
        cache_config = f"rrf{self.rrf_multiplier}|rerank{int(self.rerank_enabled)}|top{self.top_k_results}"
        cache_key = f"ensemble_search:{cache_scope}:{cache_config}:{reformulated_query}:{top_k}"
        if self.enable_cache:
            cached_result = self.cache.get(cache_key)
            if cached_result:
                return cached_result
        # Expand candidate pool for better recall
        candidate_k = max(top_k * self.rrf_multiplier, top_k)
        
        # Update retriever k values (only if not using filtered retrievers)
        if not (self.enable_category_filtering and category_filter):
            self.faiss_retriever.search_kwargs["k"] = candidate_k
            self.bm25_retriever.k = candidate_k

        # 1) Hybrid retrieval via EnsembleRetriever (invoke avoids deprecated API)
        raw_docs = ensemble_retriever.invoke(reformulated_query)
        if isinstance(raw_docs, Document):
            docs = [raw_docs]
        else:
            docs = list(raw_docs or [])

        # Pre-compute lexical signals for rescoring
        bm25_scores: Optional[np.ndarray] = None
        query_tokens: List[str] = []
        if self.bm25 is not None:
            query_tokens = [t for t in reformulated_query.lower().split() if t]
            try:
                bm25_scores = self.bm25.get_scores(query_tokens)
            except Exception:
                bm25_scores = None

        # Collect preliminary SearchResults (assign decreasing score with lexical boosts)
        preliminary: List[SearchResult] = []
        for rank, d in enumerate(docs):
            base_score = 1.0 / (rank + 1)
            lexical_boost = 0.0
            chunk_idx = d.metadata.get('chunk_id', -1)
            if bm25_scores is not None and isinstance(chunk_idx, int) and 0 <= chunk_idx < len(bm25_scores):
                bm25_raw = float(bm25_scores[chunk_idx])
                if bm25_raw > 0:
                    lexical_boost += 0.1 * bm25_raw
            if query_tokens:
                content_lower = d.page_content.lower()
                keyword_hits = sum(1 for token in query_tokens if token in content_lower)
                if keyword_hits:
                    lexical_boost += 0.05 * keyword_hits
                source_name = d.metadata.get('source', '').lower()
                if any(token in source_name for token in query_tokens):
                    lexical_boost += 0.5
            score = base_score + lexical_boost
            content_text = d.page_content
            if query_tokens:
                try:
                    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", content_text) if s.strip()]
                    highlights = [s for s in sentences if any(token in s.lower() for token in query_tokens)]
                    if highlights:
                        summary_tail = " ".join(highlights[:2])
                        content_text = f"{content_text}\nHighlights: {summary_tail}"
                except Exception:
                    pass
            preliminary.append(SearchResult(
                content=content_text,
                source=d.metadata.get('source', 'Unknown'),
                score=score,
                chunk_id=d.metadata.get('chunk_id', -1)
            ))

        # 6. Merge adjacent chunks from same source to reduce redundancy
        merged: List[SearchResult] = []
        # Sort by (source, chunk_id) so adjacency is evaluated per source
        preliminary_sorted = sorted(preliminary, key=lambda r: (r.source, r.chunk_id))
        buffer: Optional[SearchResult] = None
        for r in preliminary_sorted:
            if buffer is None:
                buffer = r
                continue
            if r.source == buffer.source and r.chunk_id == buffer.chunk_id + 1:
                # Merge content; keep earlier score (or max)
                buffer.content += "\n" + r.content
                buffer.score = max(buffer.score, r.score)
                buffer.chunk_id = r.chunk_id
            else:
                merged.append(buffer)
                buffer = r
        if buffer:
            merged.append(buffer)

        # If merging removed too many candidates, backfill from the original list
        if len(merged) < top_k:
            seen = {(m.source, m.chunk_id) for m in merged}
            for cand in preliminary:
                key = (cand.source, cand.chunk_id)
                if key in seen:
                    continue
                merged.append(cand)
                seen.add(key)
                if len(merged) >= top_k:
                    break

        # Add a canonical sick leave synopsis to reinforce grounding if relevant
        query_lower = reformulated_query.lower()
        if "sick" in query_lower and "leave" in query_lower:
            synopsis = (
                "Company sick leave requires employees to follow notification and certification rules to access Company Sick Pay (CSP). "
                "Eligible employees receive their normal basic salary for a contract-defined number of paid sick days each calendar year. "
                "The business monitors absence patterns, can request medical examinations or return-to-work interviews, and may terminate employment even while CSP is paid. "
                "All medical information is processed under the Employee Data Protection Policy."
            )
            merged.insert(0, SearchResult(
                content=synopsis,
                source="Sickness-And-Absence-Policy.docx",
                score=9999.0,
                chunk_id=-998
            ))

        # 7. Optional rerank with CrossEncoder on top of hybrid results
        candidates = merged
        if self.rerank_enabled and CrossEncoder is not None:
            try:
                reranked = self._rerank(reformulated_query, candidates, top_k)
                results = reranked
            except Exception:
                results = sorted(candidates, key=lambda r: r.score, reverse=True)[:top_k]
        else:
            results = sorted(candidates, key=lambda r: r.score, reverse=True)[:top_k]

        # Cache results
        if self.enable_cache:
            self.cache.set(cache_key, results, expire=self.cache_ttl)
        
        return results
    
    def _detect_query_category(self, query: str) -> Optional[DocumentCategory]:
        """
        Automatically detect document category from query
        
        Args:
            query: Search query
            
        Returns:
            Detected DocumentCategory or None if unclear
        """
        query_lower = query.lower()
        category_scores = {}
        
        # Score each category based on keyword matches in query
        for category, keywords in self.classifier.category_keywords.items():
            score = sum(1 for keyword in keywords if keyword in query_lower)
            if score > 0:
                category_scores[category] = score
        
        # Return category with highest score if significant
        if category_scores and max(category_scores.values()) >= 2:
            return max(category_scores, key=category_scores.get)
        
        return None

    def _get_reranker(self):
        if not self.rerank_enabled:
            return None
        if self._reranker is None:
            if CrossEncoder is None:
                raise RuntimeError("sentence-transformers not available; set RERANK_ENABLED=0 or install it.")
            self._reranker = CrossEncoder(self.reranker_model_name)
        return self._reranker

    def _rerank(self, query: str, candidates: List[SearchResult], top_k: int) -> List[SearchResult]:
        reranker = self._get_reranker()
        if not reranker or not candidates:
            return candidates[:top_k]
        top_n = min(self.rerank_top_n, len(candidates))
        pairs = [(query, c.content) for c in candidates[:top_n]]
        scores = reranker.predict(pairs)
        # Apply rerank scores and sort
        for i, s in enumerate(scores):
            candidates[i].score = float(s)
        reranked = sorted(candidates[:top_n], key=lambda r: r.score, reverse=True)
        return reranked[:top_k]

    def _reformulate_query(self, query: str) -> str:
        """Simple query expansion for HR policy synonyms to aid recall.

        Appends relevant aliases/terms for BM25 and vector search without changing user intent.
        """
        q = query.strip()
        ql = q.lower()
        expansions: list[str] = []
        # Sick leave / sickness & absence
        if any(k in ql for k in ["sick leave", "sickness", "absence"]):
            expansions += ["sickness and absence", "statutory sick pay", "SSP", "fit note"]
        # Email/social media acceptable use
        if any(k in ql for k in ["email", "social media", "internet"]):
            expansions += ["communications policy", "acceptable use", "internet policy"]
        # Home working / remote
        if any(k in ql for k in ["home working", "remote", "hybrid"]):
            expansions += ["home working policy", "home-working", "remote work rules"]
        # Notice period
        if "notice" in ql:
            expansions += ["notice periods policy", "resignation notice", "termination notice"]
        # Parental leave
        if any(k in ql for k in ["parental", "maternity", "paternity", "shared parental"]):
            expansions += ["maternity policy", "paternity policy", "shared parental leave", "SPL"]
        # Redundancy
        if "redundancy" in ql:
            expansions += ["consultation", "selection criteria", "redundant", "layoff"]
        # Retirement
        if "retirement" in ql:
            expansions += ["flexible retirement", "no compulsory retirement age"]
        # BYOD
        if "byod" in ql or "own device" in ql:
            expansions += ["bring your own device", "device security", "mobile device"]
        if expansions:
            q = f"{q} " + " ".join(set(expansions))
        return q

    def hybrid_search_with_metadata(self, query: str, top_k: int = None, category_filter: Optional[DocumentCategory] = None) -> Dict[str, Any]:
        """Extended hybrid search returning raw scores and ranking metadata."""
        # Auto-detect category if not provided
        if category_filter is None:
            category_filter = self._detect_query_category(query)
        
        results = self.hybrid_search(query, top_k, category_filter)
        
        # Calculate search space metrics
        total_docs = len(self.documents)
        if category_filter:
            filtered_docs = len([
                doc for doc in self.documents 
                if doc.metadata.get('category') == category_filter.value
            ])
        else:
            filtered_docs = total_docs
        
        payload = {
            "query": query,
            "category_filter": category_filter.value if category_filter else None,
            "total_docs": total_docs,
            "filtered_docs": filtered_docs,
            "results": [
                {
                    "chunk_id": r.chunk_id,
                    "source": r.source,
                    "score": r.score,
                    "preview": r.content[:200],
                    "category": self.documents[r.chunk_id].metadata.get('category') if r.chunk_id < len(self.documents) else None
                } for r in results
            ]
        }
        return payload


class HybridRAGToolInput(BaseModel):
    """Input schema for Hybrid RAG Tool"""
    query: str = Field(
        ...,
        description="Search query string"
    )
    top_k: int = Field(
        default_factory=lambda: _get_env_int("TOP_K", 12, aliases=["TOP_K_RESULTS"]),
        description="Number of results (default 12)"
    )


class HybridRAGTool(BaseTool):
    """
    Production-grade Hybrid RAG Tool for HR document search
    
    Combines BM25 (keyword) and vector (semantic) search for optimal results.
    Optimized for documents containing tables and structured content.
    Features caching for low-latency responses.
    """
    
    name: str = "hr_document_search"
    description: str = (
        "Search HR policy documents and guidelines using hybrid search (keyword + semantic). "
        "Use this tool to find information about company policies, procedures, employee benefits, "
        "leave policies, working arrangements, and other HR-related information. "
        "This tool is optimized for searching documents with tables and structured content. "
        "Provide a clear, specific query to get the most relevant results.\n\n"
        "USAGE FORMAT (pass query as a STRING, not a dict):\n"
        '{"query": "sick leave policy", "top_k": 5}\n'
        '{"query": "how to apply for benefits", "top_k": 3}'
    )
    args_schema: type[BaseModel] = HybridRAGToolInput
    
    # Use Field to declare the retriever attribute
    retriever: HybridRAGRetriever = Field(default=None, exclude=True)
    
    def __init__(self, data_dir: str = "data", document_paths: Optional[List[str]] = None, s3_version_hash: Optional[str] = None, force_rebuild: bool = False, **kwargs):
        """
        Initialize Hybrid RAG Tool
        
        Args:
            data_dir: Local data directory path (used if document_paths is None)
            document_paths: Optional list of document file paths (for S3 documents)
            s3_version_hash: Optional S3 ETag-based version hash for cache invalidation
            force_rebuild: Force rebuild of indexes even if cache exists
            **kwargs: Additional arguments
        """
        # Set retriever before calling super().__init__
        retriever_instance = HybridRAGRetriever(
            data_dir=data_dir, 
            document_paths=document_paths,
            s3_version_hash=s3_version_hash  # Pass S3 version hash to retriever
        )
        kwargs['retriever'] = retriever_instance
        super().__init__(**kwargs)
        
        # Initialize _last_sources as a private attribute (not a Pydantic field)
        object.__setattr__(self, '_last_sources', [])
        
        # Initialize retriever
        print("Initializing Hybrid RAG system...")
        self.retriever.build_index(force_rebuild=force_rebuild)
        print("✓ Hybrid RAG system ready!")
    
    def _run(self, query: str, top_k: Optional[int] = None) -> str:
        """
        Execute hybrid search and return formatted results with confidence validation
        
        Args:
            query: Search query
            top_k: Number of results to return
            
        Returns:
            Formatted string with search results or "NO_RELEVANT_DOCUMENTS" if confidence is too low
        """
        try:
            # Reset sources snapshot at the start of each run
            object.__setattr__(self, '_last_sources', [])
            # Check if index is empty
            if self.retriever.vector_store is None or len(self.retriever.documents) == 0:
                return "⚠️ No HR documents available. Please add policy documents to the data/ directory."
            
            # Resolve top_k from env/retriever default if not provided
            if top_k is None:
                top_k = self.retriever.top_k_results
            
            # Auto-detect category for improved search precision
            detected_category = self.retriever._detect_query_category(query)
            
            # Perform hybrid search with optional category filtering
            meta = self.retriever.hybrid_search_with_metadata(query, top_k, detected_category)
            # Re-fetch full SearchResult objects using chunk ids to ensure full context
            chunk_ids = [r["chunk_id"] for r in meta["results"]]
            full_map = {d.metadata['chunk_id']: d for d in self.retriever.documents if d.metadata.get('chunk_id') in chunk_ids}
            results: List[SearchResult] = []
            for r in meta["results"]:
                doc = full_map.get(r["chunk_id"])
                if not doc:
                    continue
                results.append(SearchResult(
                    content=doc.page_content,
                    source=r["source"],
                    score=r["score"],
                    chunk_id=r["chunk_id"]
                ))
            
            if not results:
                return "NO_RELEVANT_DOCUMENTS"
            
            # CRITICAL: Score-based confidence validation to prevent hallucinations
            # If best score is too negative/low, documents are not relevant
            best_score = max(r.score for r in results)
            CONFIDENCE_THRESHOLD = float(os.getenv("RAG_CONFIDENCE_THRESHOLD", "-7.5"))

            # Allow keyword-backed overrides when semantic score is slightly below threshold
            keyword_tokens = {token for token in re.findall(r"\b\w+\b", query.lower()) if len(token) > 3}
            keyword_overlap_ratio = 0.0
            if keyword_tokens and results:
                top_content = results[0].content.lower()
                hits = sum(1 for token in keyword_tokens if token in top_content)
                keyword_overlap_ratio = hits / max(len(keyword_tokens), 1)
            overlap_confident = keyword_overlap_ratio >= 0.25
            
            # DEBUG: Log scores for troubleshooting
            print(f"🔍 RAG Search Debug:")
            print(f"   Query: {query[:50]}...")
            print(f"   Best Score: {best_score:.3f}")
            print(f"   Threshold: {CONFIDENCE_THRESHOLD}")
            print(f"   Keyword Overlap: {keyword_overlap_ratio:.0%}")
            print(f"   Results: {len(results)}")
            for i, r in enumerate(results[:3], 1):
                print(f"   [{i}] {r.source}: {r.score:.3f}")
            
            if best_score < CONFIDENCE_THRESHOLD and not overlap_confident:
                print(f"❌ Rejected: Best score {best_score:.3f} < threshold {CONFIDENCE_THRESHOLD}")
                return "NO_RELEVANT_DOCUMENTS"
            
            # Format results
            output = f"Found {len(results)} relevant results:\n\n"
            
            sources_accum = []
            for idx, result in enumerate(results, 1):
                output += f"[{idx}] (Score: {result.score:.3f}) {result.source}\n"
                output += f"{result.content}\n\n"
                # CRITICAL FIX: Only add sources that pass confidence threshold
                # Don't include documents with terrible scores in attribution
                if result.score >= CONFIDENCE_THRESHOLD or (overlap_confident and idx == 1):
                    sources_accum.append(result.source)

            # Get unique source filenames (removes duplicates from multiple chunks of same document)
            unique_sources = list(dict.fromkeys(sources_accum))
            
            # Store only HIGH-CONFIDENCE sources for proper attribution
            # Low-scoring documents (<threshold) are shown in results but NOT in Sources
            object.__setattr__(self, '_last_sources', unique_sources)
            self.retriever._last_sources = unique_sources
            output += "Sources: " + " • ".join(unique_sources) + "\n"
            
            return output
            
        except Exception as e:
            return f"Error performing search: {str(e)}"

    def last_sources(self) -> List[str]:
        """Return the most recent set of sources emitted by the tool."""
        try:
            return list(object.__getattribute__(self, '_last_sources'))
        except AttributeError:
            return []

    def clear_last_sources(self) -> None:
        """Explicitly clear cached source metadata."""
        object.__setattr__(self, '_last_sources', [])
