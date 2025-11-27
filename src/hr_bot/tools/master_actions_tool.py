"""
Master Actions Tool - Hybrid RAG for Procedural Actions
Handles queries about HOW TO perform actions in HR systems (DarwinBox, SumTotal, etc.)
Dynamically loads and indexes Master Document from S3 using same RAG approach as HybridRAGTool
"""
import os
import pickle
import hashlib
import re
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from langchain.schema import Document
from langchain_community.document_loaders import Docx2txtLoader
from rank_bm25 import BM25Okapi
from diskcache import Cache

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


@dataclass
class ActionSearchResult:
    """Search result with metadata for action queries"""
    content: str
    source: str
    score: float
    chunk_id: int


class MasterActionsRetriever:
    """
    Hybrid retriever for Master Actions Document using BM25 + Vector search
    Same architecture as HybridRAGRetriever but focused on procedural/action content
    """
    
    # Confidence threshold for action search results (0.0 - 1.0)
    # Results below this score are considered low-confidence and filtered out
    CONFIDENCE_THRESHOLD: float = float(os.getenv("MASTER_ACTIONS_CONFIDENCE_THRESHOLD", "0.3"))
    
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        document_paths: Optional[List[str]] = None,
        s3_version_hash: Optional[str] = None
    ):
        """
        Initialize Master Actions Retriever
        
        Args:
            cache_dir: Directory containing cached S3 documents
            document_paths: Optional list of document file paths (for S3 documents)
            s3_version_hash: Optional S3 ETag-based version hash for cache invalidation
        """
        # Use same embeddings as HybridRAGTool for consistency
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={'device': 'cpu', 'trust_remote_code': False},
            encode_kwargs={'normalize_embeddings': True}
        )
        
        # Core indices
        self.vector_store = None
        self.bm25 = None
        self.bm25_retriever = None
        self.faiss_retriever = None
        self.ensemble_retriever = None
        self.documents: List[Document] = []
        
        # Configuration
        self.cache_dir = cache_dir
        self.document_paths = document_paths
        self.s3_version_hash = s3_version_hash
        
        # Index storage
        self.index_dir = Path.home() / ".master_actions_index"
        self.index_dir.mkdir(exist_ok=True)
        self.index_hash: Optional[str] = None
        
        # Cache for search results
        self._search_cache = Cache(str(self.index_dir / "search_cache"))
        
        # Search settings (tuned for action/procedural content)
        self.chunk_size = 600  # Smaller chunks for action steps
        self.chunk_overlap = 150
        self.top_k = 5
        self.bm25_weight = 0.6  # Higher BM25 weight for keyword matching (action names)
        self.vector_weight = 0.4
        
        self._last_sources: List[str] = []
    
    def _find_master_document(self) -> Optional[Path]:
        """
        Find Master Document in cache directory or document paths
        Looks for files with 'knowledge', 'action', 'master', 'guide' in name
        """
        search_paths = []
        
        # Check cache_dir first (S3 mode)
        if self.cache_dir:
            cache_path = Path(self.cache_dir)
            if cache_path.exists():
                search_paths.append(cache_path)
        
        # Check document_paths if provided
        if self.document_paths:
            for doc_path in self.document_paths:
                p = Path(doc_path)
                if p.exists() and any(kw in p.name.lower() for kw in ['knowledge', 'action', 'master', 'guide']):
                    return p
        
        # Search in cache directories
        for base_path in search_paths:
            # Try exact name first
            exact_path = base_path / "Knowledge Bot – Action Links and Steps.docx"
            if exact_path.exists():
                return exact_path
            
            # Search for variations
            for file in base_path.glob("*.docx"):
                if any(kw in file.name.lower() for kw in ['knowledge', 'action', 'master', 'guide']):
                    return file
        
        # Fallback: check local data directory
        try:
            current_file = Path(__file__).resolve()
            project_root = current_file.parent.parent.parent.parent
            local_master = project_root / "data" / "Master-Document"
            if local_master.exists():
                for file in local_master.glob("*.docx"):
                    if any(kw in file.name.lower() for kw in ['knowledge', 'action', 'master', 'guide']):
                        return file
        except Exception:
            pass
        
        return None
    
    def _compute_version_hash(self) -> str:
        """Compute hash for cache invalidation"""
        hasher = hashlib.md5()
        
        # Use S3 version hash if available
        if self.s3_version_hash:
            hasher.update(self.s3_version_hash.encode())
        elif self.document_paths:
            for doc_path in sorted(self.document_paths):
                hasher.update(doc_path.encode())
                try:
                    mtime = Path(doc_path).stat().st_mtime
                    hasher.update(str(mtime).encode())
                except Exception:
                    pass
        
        # Include config in hash
        hasher.update(f"chunk:{self.chunk_size}|overlap:{self.chunk_overlap}".encode())
        hasher.update(b"master_actions_v2")
        
        return hasher.hexdigest()
    
    def _load_master_document(self) -> List[Document]:
        """Load Master Document and return as Document objects"""
        documents = []
        
        master_path = self._find_master_document()
        if not master_path:
            print("❌ Master Document not found in cache")
            return documents
        
        print(f"📖 Loading Master Document: {master_path.name}")
        
        try:
            loader = Docx2txtLoader(str(master_path))
            docs = loader.load()
            
            for doc in docs:
                doc.metadata['source'] = master_path.name
                doc.metadata['file_path'] = str(master_path)
                doc.metadata['type'] = 'master_actions'
                
                # Clean content
                doc.page_content = self._sanitize_content(doc.page_content)
                documents.append(doc)
            
            print(f"✅ Loaded Master Document: {master_path.name}")
            
        except Exception as e:
            print(f"❌ Error loading Master Document: {e}")
        
        return documents
    
    def _sanitize_content(self, text: str) -> str:
        """Clean placeholder tokens and normalize text"""
        if not text:
            return text
        
        # Common placeholder replacements
        replacements = {
            r"\[insert name and job title\]": "HR Representative",
            r"\[insert job title\]": "HR Representative",
            r"\[the Company\]": "the company",
            r"\[Company Name\]": "the company",
            r"\[Employee\]": "employee",
            r"\[INSERT LOGO HERE\]": "",
        }
        
        for pattern, replacement in replacements.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
        # Generic placeholder cleanup
        text = re.sub(r"\[\s*insert[^\]]*\]", "the appropriate details", text, flags=re.IGNORECASE)
        
        return text
    
    def _chunk_documents(self, documents: List[Document]) -> List[Document]:
        """Chunk documents with action-aware splitting"""
        # Use separators that preserve action blocks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n\n", "\n\n", "Action Name:", "\n", ". ", " "],
            length_function=len,
        )
        
        chunks = text_splitter.split_documents(documents)
        
        # Add chunk IDs
        for idx, chunk in enumerate(chunks):
            chunk.metadata['chunk_id'] = idx
        
        return chunks
    
    def _save_index(self, vector_path: Path, bm25_path: Path):
        """Save indexes to disk"""
        try:
            if self.vector_store:
                self.vector_store.save_local(str(vector_path))
            
            if self.bm25:
                # Clean documents before saving (remove non-picklable objects)
                clean_docs = []
                for doc in self.documents:
                    clean_doc = Document(
                        page_content=doc.page_content,
                        metadata=doc.metadata.copy()
                    )
                    clean_docs.append(clean_doc)
                
                with open(bm25_path, 'wb') as f:
                    pickle.dump({
                        'bm25': self.bm25,
                        'documents': clean_docs,
                        'index_hash': self.index_hash
                    }, f)
            
            print("✓ Master Actions index saved")
        except Exception as e:
            print(f"⚠️  Could not save Master Actions index: {e}")
    
    def _load_index(self, vector_path: Path, bm25_path: Path, current_hash: str) -> bool:
        """Load indexes from disk if valid"""
        try:
            if not vector_path.exists() or not bm25_path.exists():
                return False
            
            # Check TTL (24 hours)
            import time
            index_age_hours = (time.time() - bm25_path.stat().st_mtime) / 3600
            if index_age_hours > 24:
                print(f"⏰ Master Actions index is {index_age_hours:.1f}h old - rebuilding...")
                return False
            
            # Load and validate hash
            with open(bm25_path, 'rb') as f:
                data = pickle.load(f)
            
            if data.get('index_hash') != current_hash:
                print(f"🔄 Master Actions index hash mismatch - rebuilding...")
                return False
            
            # Load FAISS
            self.vector_store = FAISS.load_local(
                str(vector_path),
                self.embeddings,
                allow_dangerous_deserialization=True
            )
            
            # Load BM25 data
            self.bm25 = data['bm25']
            self.documents = data['documents']
            self.index_hash = data['index_hash']
            
            # Rebuild retrievers
            self._build_retrievers()
            
            print("✓ Loaded Master Actions index from disk")
            return True
            
        except Exception as e:
            print(f"Could not load Master Actions index: {e}")
            return False
    
    def _build_retrievers(self):
        """Build BM25 and FAISS retrievers after loading documents"""
        if not self.documents:
            return
        
        base_k = max(self.top_k, 5)
        
        self.faiss_retriever = self.vector_store.as_retriever(
            search_kwargs={"k": base_k * 2}
        )
        
        self.bm25_retriever = BM25Retriever.from_documents(self.documents)
        self.bm25_retriever.k = base_k * 2
        
        self.ensemble_retriever = EnsembleRetriever(
            retrievers=[self.bm25_retriever, self.faiss_retriever],
            weights=[self.bm25_weight, self.vector_weight],
        )
    
    def build_index(self, force_rebuild: bool = False):
        """Build or load hybrid search index for Master Document"""
        current_hash = self._compute_version_hash()
        
        vector_path = self.index_dir / "master_faiss_index"
        bm25_path = self.index_dir / "master_bm25_index.pkl"
        
        # Force rebuild if requested
        if force_rebuild:
            print("🔥 Force rebuild Master Actions index")
            import shutil
            if vector_path.exists():
                shutil.rmtree(vector_path)
            if bm25_path.exists():
                bm25_path.unlink()
        else:
            # Try to load existing index
            if self._load_index(vector_path, bm25_path, current_hash):
                return
        
        print("🔨 Building Master Actions index...")
        
        # Load and chunk Master Document
        raw_docs = self._load_master_document()
        if not raw_docs:
            print("⚠️  No Master Document found - tool will return NO_ACTION_FOUND")
            return
        
        self.documents = self._chunk_documents(raw_docs)
        print(f"📊 Created {len(self.documents)} chunks from Master Document")
        
        if not self.documents:
            return
        
        # Build FAISS vector store
        texts = [doc.page_content for doc in self.documents]
        metadatas = [doc.metadata for doc in self.documents]
        
        self.vector_store = FAISS.from_texts(
            texts=texts,
            embedding=self.embeddings,
            metadatas=metadatas
        )
        
        # Build BM25 index
        tokenized_corpus = [doc.page_content.lower().split() for doc in self.documents]
        self.bm25 = BM25Okapi(tokenized_corpus)
        
        # Build retrievers
        self._build_retrievers()
        
        self.index_hash = current_hash
        print(f"✅ Master Actions index built with {len(self.documents)} chunks")
        
        # Save index
        self._save_index(vector_path, bm25_path)
    
    def _expand_query(self, query: str) -> str:
        """Expand query with action-related synonyms for better recall"""
        q = query.strip().lower()
        expansions = []
        
        # Common action synonyms
        action_expansions = {
            'apply': ['request', 'submit', 'file'],
            'download': ['get', 'access', 'view', 'fetch'],
            'leave': ['vacation', 'time off', 'absence', 'pto'],
            'payslip': ['salary slip', 'pay stub', 'salary statement'],
            'profile': ['personal details', 'employee info', 'my details'],
            'training': ['learning', 'course', 'certification', 'skill'],
            'expense': ['reimbursement', 'claim', 'travel claim'],
            'attendance': ['punch', 'check in', 'clock'],
            'holiday': ['calendar', 'public holiday', 'company holiday'],
            'form-16': ['tax form', 'income tax', 'tds'],
            'balance': ['remaining', 'available', 'quota'],
        }
        
        for keyword, synonyms in action_expansions.items():
            if keyword in q:
                expansions.extend(synonyms)
        
        if expansions:
            return f"{query} {' '.join(set(expansions))}"
        return query
    
    def search(self, query: str, top_k: Optional[int] = None) -> List[ActionSearchResult]:
        """
        Perform hybrid search for action-related content
        
        Args:
            query: User's query about HOW TO perform an action
            top_k: Number of results to return
            
        Returns:
            List of ActionSearchResult objects
        """
        if not self.vector_store or not self.ensemble_retriever or not self.documents:
            print("⚠️  Master Actions index not built - no results")
            return []
        
        top_k = top_k or self.top_k
        
        # Expand query for better recall
        expanded_query = self._expand_query(query)
        
        # Check cache
        cache_key = f"master_search:{self.index_hash}:{expanded_query}:{top_k}"
        cached = self._search_cache.get(cache_key)
        if cached:
            return cached
        
        # Perform hybrid search
        try:
            raw_docs = self.ensemble_retriever.invoke(expanded_query)
            docs = list(raw_docs) if raw_docs else []
        except Exception as e:
            print(f"⚠️  Search error: {e}")
            return []
        
        if not docs:
            return []
        
        # Score and rank results
        query_tokens = set(re.findall(r'\b\w+\b', query.lower()))
        stop_words = {'a', 'an', 'the', 'is', 'are', 'to', 'for', 'of', 'in', 'on', 'how', 'what', 'i', 'my', 'can'}
        query_tokens -= stop_words
        
        results = []
        for rank, doc in enumerate(docs):
            base_score = 1.0 / (rank + 1)
            
            # Boost for keyword matches
            content_lower = doc.page_content.lower()
            keyword_hits = sum(1 for token in query_tokens if token in content_lower)
            keyword_boost = 0.1 * keyword_hits
            
            # Boost for action-related keywords in content
            action_markers = ['link:', 'steps:', 'step 1', 'step 2', 'click', 'navigate', 'select', 'action name:']
            action_boost = 0.2 if any(marker in content_lower for marker in action_markers) else 0
            
            score = base_score + keyword_boost + action_boost
            
            results.append(ActionSearchResult(
                content=doc.page_content,
                source=doc.metadata.get('source', 'Master Actions Guide'),
                score=score,
                chunk_id=doc.metadata.get('chunk_id', -1)
            ))
        
        # Sort by score and limit
        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:top_k]
        
        # Cache results
        self._search_cache.set(cache_key, results, expire=3600)
        
        return results


class MasterActionsToolInput(BaseModel):
    """Input schema for Master Actions Tool"""
    query: str = Field(
        ...,
        description="The query about HOW TO perform an action (e.g., 'how to apply leave', 'download payslip')"
    )


class MasterActionsTool(BaseTool):
    """
    Master Actions Tool - Hybrid RAG for Procedural Actions
    
    Dynamically loads Master Document from S3 and uses same RAG approach
    as HybridRAGTool for sustainable, maintainable action search.
    
    Use this tool when users ask HOW TO perform specific actions like:
    - Applying for leave
    - Downloading payslips
    - Updating personal details
    - Enrolling in training
    - Checking leave balance
    """
    
    name: str = "master_actions_guide"
    description: str = (
        "Provides step-by-step instructions with direct links for performing HR system actions. "
        "Use this tool when the user asks HOW TO do something specific OR when they request "
        "links/access to HR portals and resources. Examples: "
        "'how to apply leave', 'download payslip', 'update profile', 'enroll in training', "
        "'check leave balance', 'holiday calendar', 'view policies', 'access learning portal', "
        "'show me form-16', 'where can I find payslips'. "
        "ALWAYS use this tool for queries about accessing/viewing/downloading HR documents or portals. "
        "Returns actionable links and clear step-by-step procedures."
    )
    args_schema: type[BaseModel] = MasterActionsToolInput
    
    retriever: MasterActionsRetriever = Field(default=None, exclude=True)
    
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        document_paths: Optional[List[str]] = None,
        s3_version_hash: Optional[str] = None,
        force_rebuild: bool = False,
        **kwargs
    ):
        """
        Initialize MasterActionsTool with RAG-based retrieval
        
        Args:
            cache_dir: Directory containing cached S3 documents
            document_paths: Optional list of document file paths (for S3 documents)
            s3_version_hash: Optional S3 ETag-based version hash for cache invalidation
            force_rebuild: Force rebuild of indexes even if cache exists
        """
        retriever_instance = MasterActionsRetriever(
            cache_dir=cache_dir,
            document_paths=document_paths,
            s3_version_hash=s3_version_hash
        )
        kwargs['retriever'] = retriever_instance
        super().__init__(**kwargs)
        
        # Initialize _last_sources
        object.__setattr__(self, '_last_sources', [])
        
        # Build index
        print("🔧 Initializing Master Actions Tool...")
        self.retriever.build_index(force_rebuild=force_rebuild)
        print("✅ Master Actions Tool ready!")
    
    def _run(self, query: str) -> str:
        """
        Execute hybrid search for procedural actions
        
        Args:
            query: User's query about HOW TO perform an action
            
        Returns:
            Formatted string with action content, or "NO_ACTION_FOUND"
        """
        try:
            # Reset sources
            object.__setattr__(self, '_last_sources', [])
            
            # Check if index is built
            if not self.retriever.documents:
                return "NO_ACTION_FOUND"
            
            # Perform search
            results = self.retriever.search(query, top_k=5)
            
            if not results:
                return "NO_ACTION_FOUND"
            
            # Check relevance threshold
            best_score = max(r.score for r in results)
            if best_score < MasterActionsRetriever.CONFIDENCE_THRESHOLD:
                return "NO_ACTION_FOUND"
            
            # Format output
            output = f"Found {len(results)} relevant action(s):\n\n"
            
            sources = set()
            for idx, result in enumerate(results, 1):
                output += f"**[{idx}]** (Score: {result.score:.3f})\n"
                output += f"{result.content}\n\n"
                sources.add(result.source)
            
            # Store sources
            source_list = list(sources)
            object.__setattr__(self, '_last_sources', source_list)
            
            output += "Sources: " + " • ".join(source_list) + "\n"
            
            return output
            
        except Exception as e:
            return f"Error searching actions: {str(e)}"
    
    def last_sources(self) -> List[str]:
        """Return the most recent set of sources emitted by the tool."""
        try:
            return list(object.__getattribute__(self, '_last_sources'))
        except AttributeError:
            return []
    
    def clear_last_sources(self) -> None:
        """Explicitly clear cached source metadata."""
        object.__setattr__(self, '_last_sources', [])
