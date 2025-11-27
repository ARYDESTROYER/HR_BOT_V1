"""
Admin console services - data gathering and operations.
"""

import os
import json
import shutil
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger("hr_bot.admin.services")


class AdminServices:
    """Centralized admin operations and data gathering."""
    
    def __init__(self):
        self.cache_dir = Path("storage/response_cache")
        self.logs_dir = Path("data/logs")
        self.rag_index_dir = Path(".rag_index")
        self.stats_file = Path("data/admin_stats.json")
        
        # Ensure directories exist
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.stats_file.parent.mkdir(parents=True, exist_ok=True)
    
    # -------------------------------------------------------------------------
    # Dashboard Stats
    # -------------------------------------------------------------------------
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Gather all dashboard statistics in a flat format for the template."""
        cache = self.get_cache_stats()
        rag = self.get_rag_stats()
        query = self.get_query_stats()
        
        return {
            # Query stats
            "queries_today": query.get("today", 0),
            "query_change": 0,  # TODO: calculate day-over-day change
            
            # Cache stats
            "cache_hit_rate": cache.get("hit_rate", "0%"),
            "cache_entries": cache.get("total_entries", 0),
            
            # User stats - count from env lists
            "active_users": len([e for e in os.getenv("EMPLOYEE_EMAILS", "").split(",") if e.strip()]) + \
                           len([e for e in os.getenv("EXECUTIVE_EMAILS", "").split(",") if e.strip()]),
            "total_users": len([e for e in os.getenv("EMPLOYEE_EMAILS", "").split(",") if e.strip()]) + \
                          len([e for e in os.getenv("EXECUTIVE_EMAILS", "").split(",") if e.strip()]),
            
            # Document/RAG stats
            "documents_indexed": rag.get("indexed_documents", 0),
            "last_sync": rag.get("last_rebuild", "Never"),
            
            # RAG status
            "rag_status": rag.get("status", "Unknown"),
            "employee_docs": self._count_docs_for_role("employee"),
            "executive_docs": self._count_docs_for_role("executive"),
            "vector_store_size": rag.get("index_size", "0 KB"),
            
            # Recent queries for activity feed
            "recent_queries": self.get_query_logs(limit=5),
        }
    
    def _count_docs_for_role(self, role: str) -> int:
        """Count cached documents for a role."""
        import tempfile
        cache_base = os.getenv("S3_CACHE_DIR", tempfile.gettempdir())
        cache_dir = Path(cache_base) / "hr_bot_s3_cache" / role
        
        if cache_dir.exists():
            return len([f for f in cache_dir.glob("*") if f.is_file() and not f.name.startswith(".")])
        return 0
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get semantic cache statistics."""
        stats = {
            "total_entries": 0,
            "memory_size": "0 KB",
            "disk_size": "0 KB",
            "hit_rate": "0%",
            "hits": 0,
            "misses": 0,
            "semantic_hits": 0,
            "exact_hits": 0,
        }
        
        # Read cache stats file if exists
        cache_stats_file = self.cache_dir / "cache_stats.json"
        if cache_stats_file.exists():
            try:
                with open(cache_stats_file, 'r') as f:
                    saved = json.load(f)
                    stats.update({
                        "hits": saved.get("hits", 0),
                        "misses": saved.get("misses", 0),
                        "semantic_hits": saved.get("semantic_hits", 0),
                        "exact_hits": saved.get("exact_hits", 0),
                    })
                    total = stats["hits"] + stats["misses"]
                    if total > 0:
                        stats["hit_rate"] = f"{stats['hits'] / total * 100:.1f}%"
            except Exception as e:
                logger.error(f"Error reading cache stats: {e}")
        
        # Count cache files
        if self.cache_dir.exists():
            cache_files = list(self.cache_dir.glob("*.json"))
            stats["total_entries"] = len([f for f in cache_files if f.name != "cache_stats.json"])
            
            # Calculate disk size
            total_size = sum(f.stat().st_size for f in cache_files if f.exists())
            if total_size > 1024 * 1024:
                stats["disk_size"] = f"{total_size / 1024 / 1024:.1f} MB"
            else:
                stats["disk_size"] = f"{total_size / 1024:.1f} KB"
        
        return stats
    
    def get_rag_stats(self) -> Dict[str, Any]:
        """Get RAG index statistics."""
        stats = {
            "indexed_documents": 0,
            "index_size": "0 KB",
            "last_rebuild": "Never",
            "status": "Not Built",
        }
        
        if self.rag_index_dir.exists():
            # Count files in index
            index_files = list(self.rag_index_dir.rglob("*"))
            stats["indexed_documents"] = len([f for f in index_files if f.is_file()])
            
            # Calculate size
            total_size = sum(f.stat().st_size for f in index_files if f.is_file())
            if total_size > 1024 * 1024:
                stats["index_size"] = f"{total_size / 1024 / 1024:.1f} MB"
            else:
                stats["index_size"] = f"{total_size / 1024:.1f} KB"
            
            # Get last modified time
            if index_files:
                latest = max(f.stat().st_mtime for f in index_files if f.is_file())
                stats["last_rebuild"] = datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M")
                stats["status"] = "Ready"
        
        return stats
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Get system statistics."""
        import time
        
        # Try to get process start time
        uptime = "Unknown"
        try:
            import psutil
            process = psutil.Process()
            start_time = datetime.fromtimestamp(process.create_time())
            delta = datetime.now() - start_time
            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            uptime = f"{hours}h {minutes}m"
        except ImportError:
            pass  # psutil not installed
        except Exception:
            pass
        
        return {
            "uptime": uptime,
            "version": os.getenv("APP_VERSION", "6.7"),
            "environment": "production" if not os.getenv("ALLOW_DEV_LOGIN", "false").lower() == "true" else "development",
        }
    
    def get_query_stats(self) -> Dict[str, Any]:
        """Get query statistics from logs."""
        stats = {
            "today": 0,
            "total": 0,
            "avg_response_time": "N/A",
        }
        
        # Read from query log if exists
        query_log = self.logs_dir / "queries.jsonl"
        if query_log.exists():
            try:
                today = datetime.now().date()
                total = 0
                today_count = 0
                
                with open(query_log, 'r') as f:
                    for line in f:
                        total += 1
                        try:
                            entry = json.loads(line)
                            ts = datetime.fromisoformat(entry.get("timestamp", ""))
                            if ts.date() == today:
                                today_count += 1
                        except:
                            pass
                
                stats["today"] = today_count
                stats["total"] = total
            except Exception as e:
                logger.error(f"Error reading query log: {e}")
        
        return stats
    
    # -------------------------------------------------------------------------
    # Cache Operations
    # -------------------------------------------------------------------------
    
    def clear_cache(self) -> Dict[str, Any]:
        """Clear all cached responses."""
        count = 0
        if self.cache_dir.exists():
            for f in self.cache_dir.glob("*.json"):
                f.unlink()
                count += 1
        
        self._log_admin_action("clear_cache", {"entries_cleared": count})
        return {"success": True, "entries_cleared": count}
    
    def get_cache_entries(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Get paginated list of cache entries."""
        entries = []
        
        if not self.cache_dir.exists():
            return entries
        
        cache_files = sorted(
            [f for f in self.cache_dir.glob("*.json") if f.name != "cache_stats.json"],
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        for f in cache_files[offset:offset + limit]:
            try:
                with open(f, 'r') as file:
                    data = json.load(file)
                    # Get timestamp and calculate expiry
                    ts = data.get("timestamp", "")
                    created = ts
                    expires = "Unknown"
                    if ts:
                        try:
                            created_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            ttl_hours = int(os.getenv("CACHE_TTL_HOURS", "72"))
                            expires_dt = created_dt + timedelta(hours=ttl_hours)
                            created = created_dt.strftime("%Y-%m-%d %H:%M")
                            expires = expires_dt.strftime("%Y-%m-%d %H:%M")
                        except:
                            pass
                    
                    entries.append({
                        "id": f.stem,
                        "query": data.get("query_preview", data.get("query", ""))[:80],
                        "created": created,
                        "expires": expires,
                        "hits": data.get("hits", 1),
                        "size": f"{f.stat().st_size / 1024:.1f} KB"
                    })
            except Exception:
                pass
        
        return entries
    
    def delete_cache_entry(self, entry_id: str) -> bool:
        """Delete a specific cache entry."""
        cache_file = self.cache_dir / f"{entry_id}.json"
        if cache_file.exists():
            cache_file.unlink()
            self._log_admin_action("delete_cache_entry", {"entry_id": entry_id})
            return True
        return False
    
    # -------------------------------------------------------------------------
    # RAG Operations
    # -------------------------------------------------------------------------
    
    def rebuild_rag_index(self) -> Dict[str, Any]:
        """Trigger RAG index rebuild by clearing index directory."""
        if self.rag_index_dir.exists():
            shutil.rmtree(self.rag_index_dir)
        
        # Clear bot cache to force reinitialization
        from hr_bot.crew import HrBot
        HrBot.clear_rag_cache()
        
        self._log_admin_action("rebuild_rag_index", {})
        return {"success": True, "message": "RAG index cleared. Will rebuild on next query."}
    
    def test_rag_search(self, query: str) -> Dict[str, Any]:
        """Test RAG search with a query."""
        try:
            from hr_bot.tools.hybrid_rag_tool import HybridRAGTool
            
            tool = HybridRAGTool(user_role="employee")
            results = tool.retriever.hybrid_search(query, top_k=5)
            
            return {
                "success": True,
                "results": [
                    {
                        "content": r.page_content[:200] + "..." if len(r.page_content) > 200 else r.page_content,
                        "source": r.metadata.get("source", "Unknown"),
                        "score": r.metadata.get("score", 0)
                    }
                    for r in results
                ]
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # -------------------------------------------------------------------------
    # User Management
    # -------------------------------------------------------------------------
    
    def get_users(self) -> List[Dict[str, Any]]:
        """Get all configured users as a flat list."""
        users = []
        
        admin_emails = set(e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip())
        exec_emails = set(e.strip().lower() for e in os.getenv("EXECUTIVE_EMAILS", "").split(",") if e.strip())
        emp_emails = set(e.strip().lower() for e in os.getenv("EMPLOYEE_EMAILS", "").split(",") if e.strip())
        
        # All unique emails
        all_emails = admin_emails | exec_emails | emp_emails
        
        for email in sorted(all_emails):
            # Determine role (executive takes precedence)
            if email in exec_emails:
                role = "executive"
            else:
                role = "employee"
            
            users.append({
                "email": email,
                "name": email.split("@")[0].replace(".", " ").title(),
                "role": role,
                "is_admin": email in admin_emails,
                "last_active": None,  # Would need session tracking
            })
        
        return users
    
    def get_admin_emails(self) -> List[str]:
        """Get list of admin emails for display."""
        return [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]
    
    # -------------------------------------------------------------------------
    # Logs
    # -------------------------------------------------------------------------
    
    def get_query_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent query logs."""
        logs = []
        query_log = self.logs_dir / "queries.jsonl"
        
        if query_log.exists():
            try:
                with open(query_log, 'r') as f:
                    lines = f.readlines()
                    for line in reversed(lines[-limit:]):
                        try:
                            logs.append(json.loads(line))
                        except:
                            pass
            except Exception as e:
                logger.error(f"Error reading query logs: {e}")
        
        return logs
    
    def get_admin_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get admin action audit log."""
        logs = []
        audit_log = self.logs_dir / "admin_audit.jsonl"
        
        if audit_log.exists():
            try:
                with open(audit_log, 'r') as f:
                    lines = f.readlines()
                    for line in reversed(lines[-limit:]):
                        try:
                            logs.append(json.loads(line))
                        except:
                            pass
            except Exception as e:
                logger.error(f"Error reading audit logs: {e}")
        
        return logs
    
    def _log_admin_action(self, action: str, details: Dict[str, Any], admin_email: str = "unknown"):
        """Log an admin action to audit log."""
        audit_log = self.logs_dir / "admin_audit.jsonl"
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "admin": admin_email,
            "action": action,
            "details": details
        }
        
        try:
            with open(audit_log, 'a') as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Error writing audit log: {e}")
    
    # -------------------------------------------------------------------------
    # S3 Document Operations
    # -------------------------------------------------------------------------
    
    def refresh_s3_documents(self, role: str = "employee") -> Dict[str, Any]:
        """Force refresh documents from S3."""
        try:
            from hr_bot.utils.s3_loader import S3DocumentLoader
            from hr_bot.crew import HrBot
            
            loader = S3DocumentLoader(user_role=role)
            loader.clear_cache()
            document_paths = loader.load_documents(force_refresh=True)
            
            # Clear RAG index
            if self.rag_index_dir.exists():
                shutil.rmtree(self.rag_index_dir)
            
            HrBot.clear_rag_cache()
            
            self._log_admin_action("refresh_s3_documents", {
                "role": role,
                "documents_loaded": len(document_paths)
            })
            
            return {
                "success": True,
                "documents_loaded": len(document_paths),
                "message": f"Refreshed {len(document_paths)} documents from S3"
            }
        except Exception as e:
            logger.exception("S3 refresh failed")
            return {"success": False, "error": str(e)}
    
    def get_document_stats(self) -> Dict[str, Any]:
        """Get document statistics."""
        stats = {
            "total_documents": 0,
            "by_folder": {},
            "last_sync": "Never"
        }
        
        # Check S3 cache metadata
        import tempfile
        cache_base = os.getenv("S3_CACHE_DIR", tempfile.gettempdir())
        
        for role in ["employee", "executive"]:
            cache_dir = Path(cache_base) / "hr_bot_s3_cache" / role
            metadata_file = cache_dir / ".cache_metadata.json"
            
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r') as f:
                        meta = json.load(f)
                        stats["last_sync"] = meta.get("last_sync", "Unknown")
                        stats["total_documents"] = meta.get("file_count", 0)
                except:
                    pass
                break
        
        return stats


# Singleton instance
admin_services = AdminServices()
