"""
Admin Console for Inara HR Assistant
Lightweight admin dashboard using Starlette + Jinja2 + HTMX
"""

from .routes import admin_routes

__all__ = ["admin_routes"]
