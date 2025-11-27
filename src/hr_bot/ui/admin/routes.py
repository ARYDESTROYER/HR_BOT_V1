"""
Admin console routes.
Serves admin pages and API endpoints.
"""

import os
import logging
from pathlib import Path
from typing import Optional

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from .auth import get_current_user, require_admin
from .services import admin_services

logger = logging.getLogger("hr_bot.admin.routes")

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Ensure directories exist
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Jinja2 environment
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=True
)


def render_template(template_name: str, context: dict) -> str:
    """Render a Jinja2 template."""
    template = jinja_env.get_template(template_name)
    return template.render(**context)


# -----------------------------------------------------------------------------
# Page Routes
# -----------------------------------------------------------------------------

async def dashboard(request: Request) -> HTMLResponse:
    """Main admin dashboard."""
    # Check auth
    redirect = require_admin(request)
    if redirect:
        return redirect
    
    user = get_current_user(request)
    stats = admin_services.get_dashboard_stats()
    
    return HTMLResponse(render_template("dashboard.html", {
        "user": user,
        "stats": stats,
        "page": "dashboard"
    }))


async def cache_page(request: Request) -> HTMLResponse:
    """Cache management page."""
    redirect = require_admin(request)
    if redirect:
        return redirect
    
    user = get_current_user(request)
    cache_stats = admin_services.get_cache_stats()
    entries = admin_services.get_cache_entries(limit=50)
    
    return HTMLResponse(render_template("cache.html", {
        "user": user,
        "stats": cache_stats,
        "entries": entries,
        "page": "cache"
    }))


async def users_page(request: Request) -> HTMLResponse:
    """User management page."""
    redirect = require_admin(request)
    if redirect:
        return redirect
    
    user = get_current_user(request)
    users = admin_services.get_users()
    admin_emails = admin_services.get_admin_emails()
    
    return HTMLResponse(render_template("users.html", {
        "user": user,
        "users": users,
        "admin_emails": admin_emails,
        "page": "users"
    }))


async def logs_page(request: Request) -> HTMLResponse:
    """Logs viewer page."""
    redirect = require_admin(request)
    if redirect:
        return redirect
    
    user = get_current_user(request)
    query_logs = admin_services.get_query_logs(limit=100)
    audit_logs = admin_services.get_admin_audit_log(limit=50)
    
    return HTMLResponse(render_template("logs.html", {
        "user": user,
        "query_logs": query_logs,
        "audit_logs": audit_logs,
        "page": "logs"
    }))


async def rag_page(request: Request) -> HTMLResponse:
    """RAG index management page."""
    redirect = require_admin(request)
    if redirect:
        return redirect
    
    user = get_current_user(request)
    rag_stats = admin_services.get_rag_stats()
    doc_stats = admin_services.get_document_stats()
    
    return HTMLResponse(render_template("rag.html", {
        "user": user,
        "rag_stats": rag_stats,
        "doc_stats": doc_stats,
        "page": "rag"
    }))


async def settings_page(request: Request) -> HTMLResponse:
    """Settings page."""
    redirect = require_admin(request)
    if redirect:
        return redirect
    
    user = get_current_user(request)
    
    # Get relevant settings (non-sensitive)
    settings = {
        "APP_NAME": os.getenv("APP_NAME", "Inara"),
        "APP_DESCRIPTION": os.getenv("APP_DESCRIPTION", "your intelligent assistant"),
        "CACHE_TTL_HOURS": os.getenv("CACHE_TTL_HOURS", "72"),
        "CACHE_SIMILARITY_THRESHOLD": os.getenv("CACHE_SIMILARITY_THRESHOLD", "0.75"),
        "TOP_K_RESULTS": os.getenv("TOP_K_RESULTS", "12"),
        "BM25_WEIGHT": os.getenv("BM25_WEIGHT", "0.5"),
        "VECTOR_WEIGHT": os.getenv("VECTOR_WEIGHT", "0.5"),
        "SUPPORT_CONTACT_EMAIL": os.getenv("SUPPORT_CONTACT_EMAIL", ""),
    }
    
    return HTMLResponse(render_template("settings.html", {
        "user": user,
        "settings": settings,
        "page": "settings"
    }))


# -----------------------------------------------------------------------------
# API Routes (for HTMX)
# -----------------------------------------------------------------------------

async def api_stats(request: Request) -> JSONResponse:
    """Get dashboard stats as JSON."""
    redirect = require_admin(request)
    if redirect:
        return JSONResponse({"error": "Unauthorized"}, status_code=403)
    
    stats = admin_services.get_dashboard_stats()
    return JSONResponse(stats)


async def api_clear_cache(request: Request) -> HTMLResponse:
    """Clear all cache entries."""
    redirect = require_admin(request)
    if redirect:
        return HTMLResponse("<div class='text-red-400'>Unauthorized</div>", status_code=403)
    
    user = get_current_user(request)
    admin_services._log_admin_action("clear_cache", {}, user.get("email", "unknown"))
    
    result = admin_services.clear_cache()
    
    if result["success"]:
        return HTMLResponse(f"""
            <div class="bg-green-500/20 border border-green-500/50 rounded-lg p-4 text-green-300">
                ✅ Cache cleared successfully. {result['entries_cleared']} entries removed.
            </div>
        """)
    else:
        return HTMLResponse(f"""
            <div class="bg-red-500/20 border border-red-500/50 rounded-lg p-4 text-red-300">
                ❌ Failed to clear cache.
            </div>
        """)


async def api_refresh_docs(request: Request) -> HTMLResponse:
    """Refresh S3 documents."""
    redirect = require_admin(request)
    if redirect:
        return HTMLResponse("<div class='text-red-400'>Unauthorized</div>", status_code=403)
    
    user = get_current_user(request)
    admin_services._log_admin_action("refresh_s3_documents", {}, user.get("email", "unknown"))
    
    # Run for both roles
    result_emp = admin_services.refresh_s3_documents("employee")
    result_exec = admin_services.refresh_s3_documents("executive")
    
    if result_emp["success"]:
        return HTMLResponse(f"""
            <div class="bg-green-500/20 border border-green-500/50 rounded-lg p-4 text-green-300">
                ✅ {result_emp['message']}
            </div>
        """)
    else:
        return HTMLResponse(f"""
            <div class="bg-red-500/20 border border-red-500/50 rounded-lg p-4 text-red-300">
                ❌ Error: {result_emp.get('error', 'Unknown error')}
            </div>
        """)


async def api_rebuild_index(request: Request) -> HTMLResponse:
    """Rebuild RAG index."""
    redirect = require_admin(request)
    if redirect:
        return HTMLResponse("<div class='text-red-400'>Unauthorized</div>", status_code=403)
    
    user = get_current_user(request)
    admin_services._log_admin_action("rebuild_rag_index", {}, user.get("email", "unknown"))
    
    result = admin_services.rebuild_rag_index()
    
    if result["success"]:
        return HTMLResponse(f"""
            <div class="bg-green-500/20 border border-green-500/50 rounded-lg p-4 text-green-300">
                ✅ {result['message']}
            </div>
        """)
    else:
        return HTMLResponse(f"""
            <div class="bg-red-500/20 border border-red-500/50 rounded-lg p-4 text-red-300">
                ❌ Failed to rebuild index.
            </div>
        """)


async def api_test_search(request: Request) -> HTMLResponse:
    """Test RAG search."""
    redirect = require_admin(request)
    if redirect:
        return HTMLResponse("<div class='text-red-400'>Unauthorized</div>", status_code=403)
    
    form = await request.form()
    query = form.get("query", "").strip()
    
    if not query:
        return HTMLResponse("""
            <div class="bg-yellow-500/20 border border-yellow-500/50 rounded-lg p-4 text-yellow-300">
                ⚠️ Please enter a search query.
            </div>
        """)
    
    result = admin_services.test_rag_search(query)
    
    if result["success"]:
        results_html = ""
        for i, r in enumerate(result["results"], 1):
            results_html += f"""
                <div class="bg-gray-800/50 rounded-lg p-4 mb-3">
                    <div class="text-sm text-gray-400 mb-2">Result {i} - {r['source']}</div>
                    <div class="text-gray-200">{r['content']}</div>
                </div>
            """
        
        return HTMLResponse(f"""
            <div class="space-y-3">
                <div class="text-green-400 font-medium">Found {len(result['results'])} results:</div>
                {results_html}
            </div>
        """)
    else:
        return HTMLResponse(f"""
            <div class="bg-red-500/20 border border-red-500/50 rounded-lg p-4 text-red-300">
                ❌ Search error: {result.get('error', 'Unknown')}
            </div>
        """)


async def api_cache_stats_partial(request: Request) -> HTMLResponse:
    """Return cache stats as HTML partial for HTMX refresh."""
    redirect = require_admin(request)
    if redirect:
        return HTMLResponse("<div class='text-red-400'>Unauthorized</div>", status_code=403)
    
    stats = admin_services.get_cache_stats()
    
    return HTMLResponse(f"""
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div class="bg-gray-800/50 rounded-lg p-4">
                <div class="text-2xl font-bold text-white">{stats['total_entries']}</div>
                <div class="text-sm text-gray-400">Total Entries</div>
            </div>
            <div class="bg-gray-800/50 rounded-lg p-4">
                <div class="text-2xl font-bold text-green-400">{stats['hit_rate']}</div>
                <div class="text-sm text-gray-400">Hit Rate</div>
            </div>
            <div class="bg-gray-800/50 rounded-lg p-4">
                <div class="text-2xl font-bold text-blue-400">{stats['hits']}</div>
                <div class="text-sm text-gray-400">Cache Hits</div>
            </div>
            <div class="bg-gray-800/50 rounded-lg p-4">
                <div class="text-2xl font-bold text-gray-400">{stats['disk_size']}</div>
                <div class="text-sm text-gray-400">Disk Usage</div>
            </div>
        </div>
    """)


# -----------------------------------------------------------------------------
# Route Definitions
# -----------------------------------------------------------------------------

routes = [
    Route("/", dashboard),
    Route("/cache", cache_page),
    Route("/users", users_page),
    Route("/logs", logs_page),
    Route("/rag", rag_page),
    Route("/settings", settings_page),
    # API endpoints for HTMX
    Route("/api/stats", api_stats),
    Route("/api/cache/clear", api_clear_cache, methods=["POST"]),
    Route("/api/cache/stats", api_cache_stats_partial),
    Route("/api/docs/refresh", api_refresh_docs, methods=["POST"]),
    Route("/api/rag/rebuild", api_rebuild_index, methods=["POST"]),
    Route("/api/rag/search", api_test_search, methods=["POST"]),
]

# Create the admin app
admin_routes = Starlette(routes=routes)
