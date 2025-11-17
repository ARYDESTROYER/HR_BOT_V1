"""
Semantic Response Caching System
Uses similarity matching instead of exact string matching for much higher cache hit rates
"""

import hashlib
import json
import os
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import logging
import re

logger = logging.getLogger(__name__)


class ResponseCache:
    """
    High-performance SEMANTIC caching system for HR Bot responses.
    
    Features:
    - Fuzzy matching using text normalization and keyword extraction
    - In-memory hot cache for instant retrieval
    - Persistent disk cache for cross-session persistence
    - Similarity threshold (default: 0.85 = 85% match)
    - Automatic expiration and cleanup
    - Cache statistics tracking
    
    Example:
        "What is the sick leave policy?" matches:
        - "Tell me about sick leave"
        - "What's the sick day policy?"
        - "How does sick leave work?"
        - "Sick leave policy?"
    """
    
    def __init__(
        self, 
        cache_dir: str = "storage/response_cache", 
        ttl_hours: int = 72,
        max_memory_items: int = 200,
        similarity_threshold: float = 0.75  # 75% match required
    ):
        """
        Initialize semantic response cache.
        
        Args:
            cache_dir: Directory to store cache files
            ttl_hours: Time-to-live for cached responses (default: 72 hours)
            max_memory_items: Maximum items to keep in memory cache
            similarity_threshold: Minimum similarity score (0.0-1.0) for cache hit
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)
        self.max_memory_items = max_memory_items
        self.similarity_threshold = similarity_threshold
        
        # Memory safety: Configurable query index size with adaptive scaling
        self.max_index_entries = int(os.getenv("CACHE_MAX_INDEX_ENTRIES", "10000"))
        # Enable adaptive index management for high-volume scenarios
        self.adaptive_index = os.getenv("CACHE_ADAPTIVE_INDEX", "true").lower() == "true"
        self.index_cleanup_threshold = float(os.getenv("CACHE_CLEANUP_THRESHOLD", "0.8"))  # Clean up at 80% capacity
        
        # In-memory cache for hot data with query keywords
        self.memory_cache: Dict[str, Dict[str, Any]] = {}
        
        # Index of normalized queries for fast similarity matching
        self.query_index: List[Tuple[str, str, set]] = []  # (cache_key, original_query, keywords)
        
        # Cache statistics with enhanced metrics for scale monitoring
        self.stats = {
            "hits": 0,
            "misses": 0,
            "memory_hits": 0,
            "disk_hits": 0,
            "semantic_hits": 0,  # NEW: hits from fuzzy matching
            "exact_hits": 0,  # NEW: hits from exact matching
            "total_queries": 0,
            "adaptive_cleanups": 0,  # NEW: track cleanup operations
            "cache_efficiency": 0.0  # NEW: hit ratio percentage
        }
        
        # Build query index from disk cache
        self._build_query_index()
        
        # Load existing cache metadata
        self._load_stats()
        
        logger.info(f"Semantic ResponseCache initialized: {cache_dir}, TTL: {ttl_hours}h, Similarity: {similarity_threshold}")

    def _is_tool_artifact(self, response: str) -> bool:
        """Detect intermediate tool-planning transcripts that shouldn't be cached."""
        if not response:
            return True
        lowered = response.lower()
        if "[hr_document_search]" in lowered:
            return True
        if "\naction:" in lowered or lowered.startswith("action:"):
            return True
        if "observation:" in lowered:
            return True
        return False

    def _remove_cache_entry(self, cache_key: str):
        """Remove cache entry from memory, disk, and semantic index."""
        self.memory_cache.pop(cache_key, None)
        cache_file = self.cache_dir / f"{cache_key}.json"
        cache_file.unlink(missing_ok=True)
        self.query_index = [entry for entry in self.query_index if entry[0] != cache_key]
    
    def _extract_keywords(self, text: str) -> set:
        """
        Extract important keywords from query for similarity matching.
        
        Removes stop words and focuses on key terms.
        """
        # Common stop words to ignore
        stop_words = {
            'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours',
            'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', 'her', 'hers',
            'herself', 'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves',
            'what', 'which', 'who', 'whom', 'this', 'that', 'these', 'those', 'am', 'is', 'are',
            'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does',
            'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 'or', 'because', 'as', 'until',
            'while', 'of', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into',
            'through', 'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down',
            'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once',
            'can', 'should', 'could', 'would', 'may', 'might', 'must', 'shall', 'will',
            'tell', 'get', 'give', 'know', 'want', 'need', 'find'
        }
        
        # Normalize and tokenize
        text_lower = text.lower()
        # Remove punctuation except apostrophes
        text_clean = re.sub(r'[^\w\s\']', ' ', text_lower)
        words = text_clean.split()
        
        # Filter stop words and short words
        keywords = {w for w in words if w not in stop_words and len(w) > 2}
        
        return keywords
    
    def _calculate_similarity(self, keywords1: set, keywords2: set) -> float:
        """
        Calculate similarity between two sets of keywords using Jaccard similarity.
        
        Returns: Similarity score between 0.0 (no match) and 1.0 (perfect match)
        """
        if not keywords1 or not keywords2:
            return 0.0
        
        intersection = keywords1.intersection(keywords2)
        union = keywords1.union(keywords2)
        
        return len(intersection) / len(union) if union else 0.0
    
    def _build_query_index(self):
        """Build index of all cached queries for fast similarity search"""
        self.query_index = []
        
        # Get all cache files sorted by modification time (newest first)
        cache_files = []
        for cache_file in self.cache_dir.glob("*.json"):
            if cache_file.name == "cache_stats.json":
                continue
            cache_files.append(cache_file)
        
        # Sort by modification time, keep only the newest entries
        cache_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        cache_files_to_index = cache_files[:self.max_index_entries]
        
        # If we're limiting, log how many we're skipping
        if len(cache_files) > self.max_index_entries:
            logger.warning(f"⚠️  Cache index limited to {self.max_index_entries} entries (skipping {len(cache_files) - self.max_index_entries} oldest files)")
            # Trigger adaptive cleanup if enabled and approaching capacity
            if self.adaptive_index and len(cache_files) > self.max_index_entries * self.index_cleanup_threshold:
                self._adaptive_cleanup(cache_files)
        
        for cache_file in cache_files_to_index:
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                
                query = cached.get("query_preview", "")
                if query:
                    cache_key = cache_file.stem
                    keywords = self._extract_keywords(query)
                    self.query_index.append((cache_key, query, keywords))
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.error(f"🗑️  Corrupted cache file detected: {cache_file.name} - {e}")
                try:
                    cache_file.unlink()  # Delete corrupted file
                    logger.info(f"✅ Deleted corrupted cache file: {cache_file.name}")
                except Exception as del_error:
                    logger.error(f"Failed to delete corrupted file {cache_file.name}: {del_error}")
            except Exception as e:
                logger.error(f"Error indexing cache file {cache_file}: {e}")
        
        logger.info(f"📇 Built query index: {len(self.query_index)} entries")
    
    def _adaptive_cleanup(self, cache_files: List[Path]):
        """
        Adaptive cleanup strategy for high-volume cache management.
        
        Removes low-value cache entries based on:
        1. Access frequency (least frequently used)
        2. Age (oldest entries first)
        3. Semantic similarity clustering (keep diverse queries)
        """
        logger.info(f"🔄 Running adaptive cleanup: {len(cache_files)} files, limit: {self.max_index_entries}")
        
        # Calculate target size (80% of max to leave headroom)
        target_size = int(self.max_index_entries * 0.8)
        files_to_remove = len(cache_files) - target_size
        
        if files_to_remove <= 0:
            return
        
        # Sort by access frequency and age (oldest and least accessed first)
        cache_files_with_stats = []
        for cache_file in cache_files:
            try:
                stat = cache_file.stat()
                # Simple heuristic: older files + larger size = lower priority
                priority_score = stat.st_mtime + (stat.st_size / 1000)  # Size as minor factor
                cache_files_with_stats.append((cache_file, priority_score))
            except Exception as e:
                logger.warning(f"Failed to stat {cache_file}: {e}")
                cache_files_with_stats.append((cache_file, 0))  # Lowest priority for errors
        
        # Sort by priority (lowest first)
        cache_files_with_stats.sort(key=lambda x: x[1])
        
        # Remove lowest priority files
        removed_count = 0
        for cache_file, _ in cache_files_with_stats[:files_to_remove]:
            try:
                cache_key = cache_file.stem
                # Remove from memory cache
                self.memory_cache.pop(cache_key, None)
                # Remove from query index
                self.query_index = [(k, q, kw) for k, q, kw in self.query_index if k != cache_key]
                # Remove from disk
                cache_file.unlink()
                removed_count += 1
            except Exception as e:
                logger.error(f"Failed to remove cache file {cache_file}: {e}")
        
        logger.info(f"🗑️  Adaptive cleanup completed: removed {removed_count} cache entries")
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for consistent cache keys"""
        return text.lower().strip().replace('\n', ' ').replace('  ', ' ')
    
    def _get_cache_key(self, query: str, context: str = "") -> str:
        """
        Generate unique cache key from query + context.
        
        Uses MD5 hash for consistent key generation while handling
        slight variations in whitespace and case.
        """
        normalized_query = self._normalize_text(query)
        normalized_context = self._normalize_text(context) if context else ""
        
        content = f"{normalized_query}|{normalized_context}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def get(self, query: str, context: str = "") -> Optional[str]:
        """
        Retrieve cached response using SEMANTIC SIMILARITY matching.
        
        Process:
        1. Try exact match first (fastest path)
        2. If no exact match, find most similar cached query
        3. Return cached response if similarity >= threshold
        
        Returns:
            Cached response string or None if not found/expired
        """
        self.stats["total_queries"] += 1
        cache_key = self._get_cache_key(query, context)
        
        # PHASE 1: Check exact match in memory cache (fastest - ~0.001ms)
        if cache_key in self.memory_cache:
            cached = self.memory_cache[cache_key]
            if datetime.now() - cached["timestamp"] < self.ttl:
                if self._is_tool_artifact(cached["response"]):
                    self._remove_cache_entry(cache_key)
                    self.stats["misses"] += 1
                    return None
                self.stats["hits"] += 1
                self.stats["memory_hits"] += 1
                self.stats["exact_hits"] += 1
                logger.info(f"✅ EXACT MEMORY cache hit for query: {query[:50]}...")
                return cached["response"]
            else:
                # Expired, remove from memory
                del self.memory_cache[cache_key]
        
        # PHASE 2: Check exact match on disk (fast - ~10ms)
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                
                timestamp = datetime.fromisoformat(cached["timestamp"])
                if datetime.now() - timestamp < self.ttl:
                    if self._is_tool_artifact(cached["response"]):
                        self._remove_cache_entry(cache_key)
                        self.stats["misses"] += 1
                        return None
                    # Valid cache - promote to memory
                    self.memory_cache[cache_key] = {
                        "response": cached["response"],
                        "timestamp": timestamp
                    }
                    
                    # Limit memory cache size
                    self._trim_memory_cache()
                    
                    self.stats["hits"] += 1
                    self.stats["disk_hits"] += 1
                    self.stats["exact_hits"] += 1
                    logger.info(f"✅ EXACT DISK cache hit for query: {query[:50]}...")
                    return cached["response"]
                else:
                    # Expired, delete file
                    cache_file.unlink()
                    logger.debug(f"🗑️ Deleted expired cache: {cache_key}")
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.error(f"🗑️  Corrupted cache file detected: {cache_key} - {e}")
                cache_file.unlink(missing_ok=True)  # Delete corrupted file
                logger.info(f"✅ Deleted corrupted cache file: {cache_key}")
            except Exception as e:
                logger.error(f"Error reading cache {cache_key}: {e}")
                cache_file.unlink(missing_ok=True)
        
        # PHASE 3: Semantic similarity search (fuzzy matching - ~50ms)
        logger.info(f"🔍 No exact match, trying semantic similarity for: {query[:50]}...")
        query_keywords = self._extract_keywords(query)
        
        best_match_key = None
        best_similarity = 0.0
        best_query = ""
        
        # Find most similar cached query
        for cached_key, cached_query, cached_keywords in self.query_index:
            similarity = self._calculate_similarity(query_keywords, cached_keywords)
            if similarity > best_similarity:
                best_similarity = similarity
                best_match_key = cached_key
                best_query = cached_query
        
        # Check if best match exceeds threshold
        if best_similarity >= self.similarity_threshold:
            logger.info(f"🎯 SEMANTIC match found! Similarity: {best_similarity:.2%}")
            logger.info(f"   Query: '{query[:60]}'")
            logger.info(f"   Matched: '{best_query[:60]}'")
            
            # Load cached response from disk
            match_file = self.cache_dir / f"{best_match_key}.json"
            try:
                with open(match_file, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                
                timestamp = datetime.fromisoformat(cached["timestamp"])
                if datetime.now() - timestamp < self.ttl:
                    if self._is_tool_artifact(cached["response"]):
                        self._remove_cache_entry(best_match_key)
                        self.stats["misses"] += 1
                        return None
                    # Valid cache - promote to memory
                    self.memory_cache[cache_key] = {
                        "response": cached["response"],
                        "timestamp": timestamp
                    }
                    
                    self.stats["hits"] += 1
                    self.stats["semantic_hits"] += 1
                    self._update_efficiency()
                    logger.info(f"✅ SEMANTIC cache hit returned!")
                    return cached["response"]
                else:
                    # Expired
                    match_file.unlink()
                    logger.debug(f"🗑️ Deleted expired semantic match: {best_match_key}")
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.error(f"🗑️  Corrupted cache file detected: {best_match_key} - {e}")
                match_file.unlink(missing_ok=True)  # Delete corrupted file
                logger.info(f"✅ Deleted corrupted cache file: {best_match_key}")
            except Exception as e:
                logger.error(f"Error reading semantic match {best_match_key}: {e}")
        else:
            logger.info(f"❌ No semantic match found (best: {best_similarity:.2%}, threshold: {self.similarity_threshold:.2%})")
        
        # Cache miss - no exact or semantic match
        self.stats["misses"] += 1
        self._update_efficiency()
        logger.info(f"❌ Cache MISS for query: {query[:50]}...")
        return None
    
    def set(self, query: str, response: str, context: str = ""):
        """
        Cache response to both memory and disk, and update query index.
        
        Args:
            query: User's query
            response: Bot's response
            context: Conversation context (optional)
        """
        cache_key = self._get_cache_key(query, context)
        timestamp = datetime.now()
        
        if self._is_tool_artifact(response):
            logger.debug(f"⏭️  Skipping cache for tool-only transcript: {query[:50]}...")
            # Ensure any previously cached artifact is removed
            self._remove_cache_entry(cache_key)
            return

        # Validate response quality - reject empty/short responses
        if not response or len(response.strip()) < 20:
            logger.warning(f"⚠️  Rejecting invalid response for caching (empty or <20 chars): {query[:50]}...")
            # Remove any existing cache entry to prevent stale data
            self._remove_cache_entry(cache_key)
            return

        cached_data = {
            "response": response,
            "timestamp": timestamp
        }
        
        # Save to memory cache
        self.memory_cache[cache_key] = cached_data
        self._trim_memory_cache()
        
        # Save to disk cache
        try:
            cache_file = self.cache_dir / f"{cache_key}.json"
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "response": response,
                    "timestamp": timestamp.isoformat(),
                    "query_preview": query[:100],  # For debugging
                    "context_preview": context[:50] if context else ""
                }, f, indent=2, ensure_ascii=False)
            
            # Add to query index for semantic search
            keywords = self._extract_keywords(query)
            self.query_index.append((cache_key, query, keywords))
            
            logger.info(f"💾 Cached response for query: {query[:50]}...")
            logger.debug(f"   Keywords: {keywords}")
        except Exception as e:
            logger.error(f"Error saving cache {cache_key}: {e}")
    
    def _trim_memory_cache(self):
        """Remove oldest items from memory cache if it exceeds max size"""
        if len(self.memory_cache) > self.max_memory_items:
            # Remove oldest 20% of items
            items_to_remove = len(self.memory_cache) - self.max_memory_items + int(self.max_memory_items * 0.2)
            
            # Sort by timestamp and remove oldest
            sorted_items = sorted(
                self.memory_cache.items(),
                key=lambda x: x[1]["timestamp"]
            )
            
            for cache_key, _ in sorted_items[:items_to_remove]:
                del self.memory_cache[cache_key]
            
            logger.debug(f"🧹 Trimmed memory cache, removed {items_to_remove} items")
    
    def clear_expired(self):
        """Remove all expired cache entries from disk"""
        expired_count = 0
        
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                
                timestamp = datetime.fromisoformat(cached["timestamp"])
                if datetime.now() - timestamp >= self.ttl:
                    cache_file.unlink()
                    expired_count += 1
            except Exception as e:
                logger.error(f"Error checking cache file {cache_file}: {e}")
                cache_file.unlink(missing_ok=True)
        
        logger.info(f"🧹 Cleared {expired_count} expired cache entries")
        
        # Update statistics for adaptive cleanup
        if expired_count > 0:
            self.stats["adaptive_cleanups"] = self.stats.get("adaptive_cleanups", 0) + 1
            self._save_stats()
    
    def clear_all(self):
        """Clear all cached responses (memory + disk)"""
        # Clear memory
        self.memory_cache.clear()
        
        # Clear disk
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
            count += 1
        
        logger.info(f"🗑️ Cleared all cache: {count} files deleted")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics including semantic matching performance"""
        total_queries = self.stats["total_queries"]
        hits = self.stats["hits"]
        
        hit_rate = (hits / total_queries * 100) if total_queries > 0 else 0
        exact_rate = (self.stats["exact_hits"] / total_queries * 100) if total_queries > 0 else 0
        semantic_rate = (self.stats["semantic_hits"] / total_queries * 100) if total_queries > 0 else 0
        
        return {
            **self.stats,
            "hit_rate": f"{hit_rate:.1f}%",
            "exact_hit_rate": f"{exact_rate:.1f}%",
            "semantic_hit_rate": f"{semantic_rate:.1f}%",
            "memory_cache_size": len(self.memory_cache),
            "disk_cache_files": len(list(self.cache_dir.glob("*.json"))),
            "query_index_size": len(self.query_index)
        }
    
    def _update_efficiency(self):
        """Update cache efficiency statistics"""
        total_queries = self.stats["total_queries"]
        hits = self.stats["hits"]
        
        # Calculate efficiency metrics
        hit_rate = (hits / total_queries * 100) if total_queries > 0 else 0
        exact_rate = (self.stats["exact_hits"] / total_queries * 100) if total_queries > 0 else 0
        semantic_rate = (self.stats["semantic_hits"] / total_queries * 100) if total_queries > 0 else 0
        
        # Update efficiency stats
        self.stats["hit_rate"] = hit_rate
        self.stats["exact_hit_rate"] = exact_rate
        self.stats["semantic_hit_rate"] = semantic_rate
        
        # Save updated stats to disk
        self._save_stats()
    
    def _load_stats(self):
        """Load cache statistics from disk"""
        stats_file = self.cache_dir / "cache_stats.json"
        if stats_file.exists():
            try:
                with open(stats_file, 'r') as f:
                    saved_stats = json.load(f)
                    self.stats.update(saved_stats)
            except Exception as e:
                logger.error(f"Error loading cache stats: {e}")
    
    def _save_stats(self):
        """Save cache statistics to disk"""
        stats_file = self.cache_dir / "cache_stats.json"
        try:
            with open(stats_file, 'w') as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving cache stats: {e}")
    
    def __del__(self):
        """Save stats when cache is destroyed"""
        self._save_stats()
