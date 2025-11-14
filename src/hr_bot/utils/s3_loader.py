"""
S3 Document Loader for Role-Based Access Control
Loads documents from S3 based on user role (executive vs employee)
Implements intelligent ETag-based caching for optimal performance and cost
"""
import os
import boto3
import tempfile
import time
import json
import hashlib
from typing import List, Optional, Tuple
from pathlib import Path
from datetime import datetime


class S3DocumentLoader:
    """
    Load documents from S3 with role-based access control and ETag-based smart caching
    
    Executive users get access to:
    - Executive-Only-Documents/
    - Regular-Employee-Documents/
    - Master-Document/
    
    Employee users get access to:
    - Regular-Employee-Documents/
    - Master-Document/
    
    Features:
    - ETag-based change detection (no downloads needed for validation)
    - Local file caching to avoid repeated S3 downloads
    - Configurable cache TTL (default: 24 hours)
    - Automatic S3 version tracking with metadata
    - Force refresh capability for manual updates
    - Production-grade cost optimization
    """
    
    def __init__(self, user_role: str = "employee", cache_ttl: int = 86400):
        """
        Initialize S3 loader with user role and smart caching
        
        Args:
            user_role: "executive" or "employee" (default: "employee")
            cache_ttl: Cache time-to-live in seconds (default: 86400 = 24 hours)
        """
        self.user_role = user_role.lower()
        self.cache_ttl = cache_ttl
        
        # S3 configuration
        self.bucket_name = os.getenv("S3_BUCKET_NAME", "hr-documents-1")
        self.region = os.getenv("S3_BUCKET_REGION", "ap-south-1")
        
        # Determine S3 prefixes based on role. We support multiple prefixes so
        # executives can access both executive + employee + master, while
        # employees access employee + master. Prefixes should end with '/'.
        exec_prefix = os.getenv("S3_EXECUTIVE_PREFIX", "executive/")
        emp_prefix = os.getenv("S3_EMPLOYEE_PREFIX", "employee/")
        master_prefix = os.getenv("S3_MASTER_PREFIX", "master/")

        if self.user_role == "executive":
            self.s3_prefixes = [p for p in (exec_prefix, emp_prefix, master_prefix) if p]
        else:
            self.s3_prefixes = [p for p in (emp_prefix, master_prefix) if p]

        # For backward-compatible single-prefix logging continue to expose
        # a representative prefix (first one)
        self.s3_prefix = self.s3_prefixes[0] if self.s3_prefixes else ""
        
        # Local cache directory
        cache_base = os.getenv("S3_CACHE_DIR", tempfile.gettempdir())
        self.cache_dir = Path(cache_base) / "hr_bot_s3_cache" / self.user_role
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Cache files
        self.manifest_file = self.cache_dir / ".cache_manifest"
        self.version_file = self.cache_dir / ".s3_version"
        self.metadata_file = self.cache_dir / ".cache_metadata.json"
        
        # Initialize S3 client
        self.s3_client = boto3.client(
            's3',
            region_name=self.region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
        )
        
        print(f"🔐 S3DocumentLoader initialized:")
        print(f"   Role: {self.user_role.upper()}")
        print(f"   S3: s3://{self.bucket_name}/{' , '.join(self.s3_prefixes)}")
        print(f"   Cache: {self.cache_dir}")
        print(f"   TTL: {cache_ttl/3600:.1f}h | ETag validation: ✅")
    
    def _get_s3_version_hash(self) -> Tuple[str, dict]:
        """
        Get version hash by comparing S3 object ETags (no downloads required)
        
        Returns:
            Tuple of (version_hash, metadata_dict)
            - version_hash: SHA256 hash of all ETags combined
            - metadata_dict: {filename: {size, last_modified, etag}}
        """
        try:
            print(f"🔍 Listing S3 objects for prefixes: {self.s3_prefixes}")

            etags = []
            metadata = {}

            # Iterate across all configured prefixes and collect metadata
            for prefix in self.s3_prefixes:
                paginator = self.s3_client.get_paginator('list_objects_v2')
                for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                    if 'Contents' not in page:
                        continue
                    for obj in page['Contents']:
                        key = obj['Key']
                        if key.endswith('.docx'):
                            etag = obj.get('ETag', '').strip('"')
                            etags.append(f"{key}:{etag}")
                            metadata[key] = {
                                'size': obj.get('Size'),
                                'last_modified': getattr(obj.get('LastModified'), 'isoformat', lambda: None)(),
                                'etag': etag
                            }

            if not etags:
                print(f"⚠️  No objects found in S3 prefixes: {self.s3_prefixes}")
                return "", {}

            # Sort for deterministic hash
            etags.sort()

            # Compute combined hash
            combined = '|'.join(etags)
            version_hash = hashlib.sha256(combined.encode()).hexdigest()

            print(f"📊 S3 Version: {version_hash[:16]}... ({len(metadata)} docs)")
            return version_hash, metadata
            
        except Exception as e:
            print(f"❌ Error computing S3 version hash: {e}")
            return "", {}
    
    def _is_cache_valid(self) -> Tuple[bool, str]:
        """
        Check if local cache is still valid using ETag-based validation
        
        Returns:
            Tuple of (is_valid, reason)
        """
        # Check if cache files exist
        if not self.manifest_file.exists():
            return False, "manifest_missing"
        
        if not self.version_file.exists():
            return False, "version_file_missing"
        
        # Check TTL expiry
        manifest_age = time.time() - self.manifest_file.stat().st_mtime
        if manifest_age > self.cache_ttl:
            return False, f"ttl_expired ({manifest_age/3600:.1f}h old)"
        
        # Check if all cached files exist
        with open(self.manifest_file, 'r') as f:
            cached_files = [Path(line.strip()) for line in f.readlines()]
        
        if not all(f.exists() for f in cached_files):
            return False, "cached_files_missing"
        
        # ETag-based validation (production-grade)
        # Compare stored S3 version hash with current S3 state
        with open(self.version_file, 'r') as f:
            cached_version = f.read().strip()
        
        current_version, _ = self._get_s3_version_hash()
        
        if not current_version:
            return False, "s3_version_check_failed"
        
        if cached_version != current_version:
            print(f"📝 S3 changed detected:")
            print(f"   Cached: {cached_version[:16]}...")
            print(f"   Current: {current_version[:16]}...")
            return False, f"s3_changed"
        
        print(f"✅ Cache valid: {len(cached_files)} files | Version: {cached_version[:16]}...")
        return True, "valid"
    
    def _get_cache_age_hours(self) -> float:
        """
        Get cache age in hours
        
        Returns:
            Cache age in hours, or infinity if cache doesn't exist
        """
        if not self.manifest_file.exists():
            return float('inf')
        
        cache_age_seconds = time.time() - self.manifest_file.stat().st_mtime
        return cache_age_seconds / 3600
    
    def _load_from_manifest(self) -> List[str]:
        """
        Load cached document paths from manifest file
        
        Returns:
            List of local file paths from manifest
        """
        if not self.manifest_file.exists():
            return []
        
        with open(self.manifest_file, 'r') as f:
            paths = [line.strip() for line in f.readlines() if line.strip()]
        
        # Verify all cached files still exist
        valid_paths = [p for p in paths if Path(p).exists()]
        
        if len(valid_paths) != len(paths):
            missing_count = len(paths) - len(valid_paths)
            print(f"⚠️  {missing_count} cached files missing, will refresh")
            return []
        
        return valid_paths
    
    def _save_manifest(self, paths: List[str]):
        """
        Save document paths to manifest file with timestamp
        
        Args:
            paths: List of local file paths to save
        """
        with open(self.manifest_file, 'w') as f:
            f.write('\n'.join(paths))
        
        print(f"💾 Saved cache manifest: {len(paths)} documents")
    
    def _save_cache_metadata(self, version_hash: str, metadata: dict):
        """
        Save S3 version hash and metadata for cache validation
        
        Args:
            version_hash: SHA256 hash of S3 ETags
            metadata: Dictionary of document metadata from S3
        """
        # Save version hash
        with open(self.version_file, 'w') as f:
            f.write(version_hash)
        
        # Save metadata
        with open(self.metadata_file, 'w') as f:
            json.dump({
                'version_hash': version_hash,
                'timestamp': time.time(),
                'document_count': len(metadata),
                'documents': metadata
            }, f, indent=2)
        
        print(f"📝 Saved cache metadata: version={version_hash[:16]}..., docs={len(metadata)}")
    
    def _list_s3_documents(self) -> List[str]:
        """
        List all document keys in S3 for the user's role
        
        Returns:
            List of S3 object keys (file paths)
        """
        try:
            documents = []

            # Track canonical document identity to avoid duplicates when the
            # same logical document exists under multiple prefixes. For
            # example:
            # - employee/Policies/Leave.docx
            # - executive/employee/Policies/Leave.docx
            # We want the first-seen (by prefix order) to win and the duplicate
            # to be skipped. Canonicalization removes the leading role-specific
            # segments for employee-scope docs so they compare equal.
            seen_canonical = set()

            for prefix in self.s3_prefixes:
                paginator = self.s3_client.get_paginator('list_objects_v2')
                for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                    if 'Contents' in page:
                        for obj in page['Contents']:
                            key = obj['Key']
                            # Only include .docx files, skip folders
                            if not (key.endswith('.docx') and not key.endswith('/')):
                                continue

                            # Compute a canonical path to identify duplicates.
                            # If the key contains '/employee/' (e.g. 'executive/employee/...')
                            # use the tail after that marker. If it starts with
                            # top-level 'employee/' use the remainder. Otherwise,
                            # fall back to the key relative to the current prefix.
                            canonical = None
                            if '/employee/' in key:
                                canonical = key.split('/employee/', 1)[1]
                            elif key.startswith('employee/'):
                                canonical = key[len('employee/'):]
                            elif key.startswith(prefix):
                                canonical = key[len(prefix):]
                            else:
                                canonical = key

                            # Normalize leading slashes
                            canonical = canonical.lstrip('/')

                            if canonical in seen_canonical:
                                # Skip duplicates; earlier prefix wins
                                continue

                            seen_canonical.add(canonical)
                            documents.append(key)

            print(f"📋 Found {len(documents)} documents in S3 for {self.user_role} role")
            return documents

        except Exception as e:
            print(f"❌ Error listing S3 documents: {e}")
            return []
    
    def _download_document(self, s3_key: str) -> Optional[str]:
        """
        Download a single document from S3 to local cache
        
        Args:
            s3_key: S3 object key (e.g., "executive/Regular-Employee-Documents/Leave_Policy.docx")
        
        Returns:
            Local file path if successful, None if failed
        """
        try:
            # Preserve S3 directory structure under the local cache directory.
            # Find which configured prefix matches this key and compute relative path.
            rel_path = None
            for prefix in self.s3_prefixes:
                if s3_key.startswith(prefix):
                    rel_path = s3_key[len(prefix):]
                    break

            # If no prefix matched, fall back to using the full key as relative path
            if rel_path is None:
                rel_path = s3_key

            local_path = self.cache_dir / Path(rel_path)
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # Download file from S3
            self.s3_client.download_file(self.bucket_name, s3_key, str(local_path))
            return str(local_path)
            
        except Exception as e:
            print(f"❌ Error downloading {s3_key}: {e}")
            return None
    
    def _download_all_from_s3(self) -> List[str]:
        """
        Download all documents from S3 to local cache
        
        Returns:
            List of local file paths
        """
        # Get all document keys from S3
        document_keys = self._list_s3_documents()
        
        if not document_keys:
            print(f"⚠️  No documents found in s3://{self.bucket_name}/{self.s3_prefix}")
            return []
        
        # Download each document
        local_paths = []
        for i, s3_key in enumerate(document_keys, 1):
            print(f"⬇️  Downloading {i}/{len(document_keys)}: {os.path.basename(s3_key)}")
            local_path = self._download_document(s3_key)
            if local_path:
                local_paths.append(local_path)
        
        print(f"✅ Downloaded {len(local_paths)} documents to cache")
        return local_paths
    
    def load_documents(self, force_refresh: bool = False) -> List[str]:
        """
        Load documents with ETag-based smart caching
        
        This method implements production-grade caching:
        1. Check if cache exists and TTL is valid
        2. Validate S3 version using ETag comparison (no downloads)
        3. If cache valid and S3 unchanged, use cached files (fast path)
        4. If cache invalid or S3 changed, download from S3 (slow path)
        5. Clear ALL RAG caches if S3 version changed (force complete RAG rebuild)
        
        Args:
            force_refresh: Force download from S3 even if cache is valid
        
        Returns:
            List of local file paths to documents
        """
        # Get current S3 version hash FIRST (before any cache checks)
        current_s3_hash, current_s3_metadata = self._get_s3_version_hash()
        
        # Check cached S3 version
        cached_s3_hash = None
        if self.version_file.exists():
            try:
                with open(self.version_file, 'r') as f:
                    cached_s3_hash = f.read().strip()
            except Exception:
                pass
        
        # Detect if S3 actually changed (critical for RAG cache invalidation)
        s3_changed = (current_s3_hash != cached_s3_hash) if cached_s3_hash else True
        
        if s3_changed and not force_refresh:
            print(f"🔄 S3 documents changed detected!")
            print(f"   Cached version: {cached_s3_hash[:12] if cached_s3_hash else 'None'}...")
            print(f"   Current version: {current_s3_hash[:12]}...")
        
        # Check if we should use cache
        if not force_refresh:
            is_valid, reason = self._is_cache_valid()
            
            if is_valid and not s3_changed:
                # Fast path: Use cached documents (S3 unchanged)
                cached_paths = self._load_from_manifest()
                
                if cached_paths:
                    cache_age = self._get_cache_age_hours()
                    print(f"⚡ Using cached documents ({len(cached_paths)} files, {cache_age:.1f}h old)")
                    return cached_paths
            else:
                if not is_valid:
                    print(f"🔄 Cache invalid: {reason}")
        else:
            print(f"🔄 Force refresh requested")
        
        # Slow path: Download from S3
        print(f"📥 Downloading documents from S3...")
        
        # Download all documents
        local_paths = self._download_all_from_s3()
        
        # Save manifest and metadata for future validation
        if local_paths:
            self._save_manifest(local_paths)
            if current_s3_hash:
                self._save_cache_metadata(current_s3_hash, current_s3_metadata)
        
        # CRITICAL: Clear ALL RAG caches if S3 changed or force refresh
        # This ensures RAG embeddings/indexes are completely rebuilt with new documents
        if s3_changed or force_refresh:
            print(f"🔥 S3 version changed - clearing ALL RAG caches...")
            self._clear_rag_cache()
        
        return local_paths
    
    def _clear_rag_cache(self):
        """
        Clear RAG index cache (FAISS/BM25) to force rebuild with new documents
        
        This is CRITICAL when S3 documents change - otherwise RAG will use old embeddings.
        We clear ALL RAG cache files, not just specific hashes, to ensure complete invalidation.
        """
        import shutil
        
        cache_dirs = [".rag_cache", ".rag_index", "storage/response_cache"]
        
        for cache_dir_name in cache_dirs:
            cache_dir = Path(cache_dir_name)
            if cache_dir.exists():
                try:
                    # Remove entire directory and recreate
                    shutil.rmtree(cache_dir)
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    print(f"🗑️  Cleared RAG cache: {cache_dir}")
                except Exception as e:
                    print(f"⚠️  Warning: Could not clear {cache_dir}: {e}")
        
        # Also clear in-memory RAG tool cache in crew.py
        try:
            from hr_bot.crew import HrBot
            HrBot.clear_rag_cache()
            print("🗑️  Cleared in-memory RAG tool cache")
        except Exception as e:
            print(f"⚠️  Warning: Could not clear in-memory cache: {e}")
        
        print("✅ All RAG caches cleared - embeddings will be rebuilt with new documents")
    
    def clear_cache(self):
        """
        Clear local cache for this role
        
        Useful for:
        - Manual cache refresh after S3 updates
        - Troubleshooting cache issues
        - Freeing disk space
        """
        import shutil
        
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            print(f"🗑️  Cleared cache: {self.cache_dir}")
        else:
            print(f"ℹ️  No cache to clear at {self.cache_dir}")
    
    def get_cache_info(self) -> dict:
        """
        Get information about the current cache
        
        Returns:
            Dictionary with cache statistics
        """
        if not self.manifest_file.exists():
            return {
                "exists": False,
                "age_hours": None,
                "file_count": 0,
                "cache_dir": str(self.cache_dir)
            }
        
        cached_paths = self._load_from_manifest()
        
        return {
            "exists": True,
            "age_hours": self._get_cache_age_hours(),
            "file_count": len(cached_paths),
            "cache_dir": str(self.cache_dir),
            "is_valid": self._is_cache_valid(),
            "ttl_hours": self.cache_ttl / 3600
        }
    
    def get_document_count(self) -> dict:
        """
        Get document count summary by folder
        
        Returns:
            Dictionary with folder names and document counts
        """
        try:
            documents = self._list_s3_documents()
            
            # Count by folder
            folder_counts = {}
            for doc in documents:
                # Extract folder from key (e.g., "executive/Regular-Employee-Documents/file.docx")
                parts = doc.split('/')
                if len(parts) >= 2:
                    folder = parts[1]  # e.g., "Regular-Employee-Documents"
                    folder_counts[folder] = folder_counts.get(folder, 0) + 1
            
            return {
                "total": len(documents),
                "by_folder": folder_counts,
                "role": self.user_role
            }
            
        except Exception as e:
            print(f"❌ Error getting document count: {e}")
            return {"total": 0, "by_folder": {}, "role": self.user_role}


def load_documents_from_s3(user_role: str = "employee", force_refresh: bool = False) -> tuple[List[str], str, str]:
    """
    Convenience function to load documents from S3 with caching
    
    Args:
        user_role: "executive" or "employee"
        force_refresh: Force download from S3 even if cache is valid
    
    Returns:
        Tuple of (file_paths, s3_version_hash, cache_dir):
        - file_paths: List of local file paths to cached/downloaded documents
        - s3_version_hash: SHA256 hash of S3 ETags for RAG cache invalidation
        - cache_dir: Directory where documents are cached (for Master Actions Tool)
    """
    loader = S3DocumentLoader(user_role=user_role)
    file_paths = loader.load_documents(force_refresh=force_refresh)
    
    # Get S3 version hash for RAG cache invalidation
    s3_version_hash, _ = loader._get_s3_version_hash()
    
    return file_paths, s3_version_hash, str(loader.cache_dir)


if __name__ == "__main__":
    # Test the loader
    from dotenv import load_dotenv
    load_dotenv()
    
    print("\n" + "="*60)
    print("Testing S3 Document Loader")
    print("="*60)
    
    # Test executive access
    print("\n🔓 EXECUTIVE ACCESS TEST:")
    exec_loader = S3DocumentLoader(user_role="executive")
    exec_count = exec_loader.get_document_count()
    print(f"Executive can access: {exec_count['total']} documents")
    print(f"Folders: {exec_count['by_folder']}")
    
    # Test employee access
    print("\n🔒 EMPLOYEE ACCESS TEST:")
    emp_loader = S3DocumentLoader(user_role="employee")
    emp_count = emp_loader.get_document_count()
    print(f"Employee can access: {emp_count['total']} documents")
    print(f"Folders: {emp_count['by_folder']}")
    
    print("\n✅ S3 Loader test complete!")
