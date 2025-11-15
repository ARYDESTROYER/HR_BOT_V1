"""
Inara - Your HR Assistant
Professional Enterprise UI - Clean, modern interface for HR policy assistance
"""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Literal
import os
import logging

import streamlit as st
from dotenv import load_dotenv, find_dotenv

from hr_bot.crew import HrBot

# Load .env so RBAC email lists are available
load_dotenv(find_dotenv(), override=False)

# (Using Streamlit built-in OIDC; no manual OAuth endpoints required)




def _clear_query_params():
    """Clear query params in a Streamlit-version-safe way."""
    try:
        # Newer Streamlit: stable API
        st.set_query_params()
    except Exception:
        try:
            # Older Streamlit: experimental API
            st.experimental_set_query_params()
        except Exception:
            # Last resort: ignore
            pass


def _set_page_mode(mode: Literal["auth", "app"]) -> None:
    """Toggle a CSS hook on the document body for auth vs. app layouts."""
    target = mode if mode in {"auth", "app"} else "app"
    st.markdown(
        f"""
        <script>
        (function() {{
            const body = window.parent?.document?.body;
            if (!body) return;
            body.classList.remove('page-auth', 'page-app');
            body.classList.add('page-{target}');
        }})();
        </script>
        """,
        unsafe_allow_html=True,
    )


# Custom in-app PKCE OAuth removed -- use Streamlit built-in `st.login()` / `st.user` only.

# ============================================================================
# AUTHENTICATION CHECK - USING STREAMLIT'S BUILT-IN OAUTH
# ============================================================================

def _env_list(key: str) -> List[str]:
    """Get list of emails from environment variable."""
    v = os.getenv(key, '')
    return [x.strip().lower() for x in v.split(',') if x.strip()]

def _derive_role(email: str) -> str:
    """Derive user role from email address."""
    e = email.strip().lower()
    if e in _env_list('EXECUTIVE_EMAILS'):
        return 'executive'
    if e in _env_list('EMPLOYEE_EMAILS'):
        return 'employee'
    return 'unauthorized'


def _get_current_email() -> Optional[str]:
    """Return the best-guess email for the current session.

    Order of precedence:
    - `st.session_state['logged_in_email']` (persisted from OAuth/dev-login)
    - `st.session_state['dev_email']` (dev fallback)
    - Attributes on `st.user`: `email`, `preferred_username`, `sub`, `name` (if contains '@')
    - Environment `DEV_TEST_EMAIL` when `ALLOW_DEV_LOGIN` is enabled
    Returns `None` if no email could be determined.
    """
    # Debug entry (print-level safe)
    try:
        # Avoid assuming st.session_state exists in all environments
        sess_email = None
        try:
            sess_email = st.session_state.get('logged_in_email')
        except Exception:
            sess_email = None
        print(f"DEBUG: _get_current_email - session logged_in_email: {sess_email}")
    except Exception:
        pass

    # 1) persisted session value (highest precedence)
    try:
        email = st.session_state.get("logged_in_email")
        if email:
            return str(email).strip().lower()
    except Exception:
        pass

    # 2) dev email in session (possible developer fallback)
    try:
        dev = st.session_state.get("dev_email")
        if dev:
            return str(dev).strip().lower()
    except Exception:
        pass

    # 3) try to extract from st.user safely (handle attribute, mapping, or other shapes)
    try:
        user_obj = getattr(st, 'user', None)
        if user_obj:
            # Preferred extraction order per requirements:
            # email -> preferred_username -> name (only if contains '@') -> sub (only if contains '@')
            # 3.a Attributes on object
            for attr in ("email", "preferred_username"):
                try:
                    if hasattr(user_obj, attr):
                        val = getattr(user_obj, attr)
                        if val:
                            sval = str(val).strip()
                            if sval:
                                return sval.lower()
                except Exception:
                    continue

            # 3.b name (only if contains '@')
            try:
                if hasattr(user_obj, 'name'):
                    val = getattr(user_obj, 'name')
                    if val:
                        sval = str(val).strip()
                        if sval and '@' in sval:
                            return sval.lower()
            except Exception:
                pass

            # 3.c sub (only if contains '@')
            try:
                if hasattr(user_obj, 'sub'):
                    val = getattr(user_obj, 'sub')
                    if val:
                        sval = str(val).strip()
                        if sval and '@' in sval:
                            return sval.lower()
            except Exception:
                pass

            # 3.d If user_obj is dict-like, check keys in the same order
            try:
                ud = None
                try:
                    ud = dict(user_obj)
                except Exception:
                    ud = None
                if isinstance(ud, dict):
                    for key in ("email", "preferred_username"):
                        if key in ud and ud[key]:
                            sval = str(ud[key]).strip()
                            if sval:
                                return sval.lower()
                    if 'name' in ud and ud['name'] and '@' in str(ud['name']):
                        return str(ud['name']).strip().lower()
                    if 'sub' in ud and ud['sub'] and '@' in str(ud['sub']):
                        return str(ud['sub']).strip().lower()
            except Exception:
                pass

            # 3.e As a last resort, scan the string representation for an email-like token
            try:
                rep = str(user_obj)
                import re
                m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", rep)
                if m:
                    return m.group(0).lower()
            except Exception:
                pass
    except Exception:
        # be conservative - don't crash the app if Streamlit user object is unexpected
        pass

    # 4) fallback to DEV_TEST_EMAIL if allowed (least precedence)
    try:
        allow_dev = os.getenv("ALLOW_DEV_LOGIN", "false").lower() in ("1", "true", "yes")
        env_dev = os.getenv("DEV_TEST_EMAIL", "").strip().lower()
        if allow_dev and env_dev:
            return env_dev
    except Exception:
        pass

    # If nothing found, return None (do not return sentinel like 'unknown')
    return None

# ============================================================================
# CONFIGURATION
# ============================================================================

PAGE_TITLE = "Inara - HR Assistant"
PAGE_ICON = None
DATA_DIR = Path("data").resolve()
DEFAULT_PLACEHOLDER = "Ask me anything about HR policies, benefits, or procedures..."
SUPPORT_CONTACT_EMAIL = os.getenv("SUPPORT_CONTACT_EMAIL", "support@company.com")
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
THEME_CSS_PATH = ASSETS_DIR / "ui.css"
WARMUP_QUERIES: List[str] = [
    "What is the sick leave policy?",
    "How do I request paternity leave?",
    "What are my vacation entitlements?",
    "How do I report an absence?",
    "What health benefits are available?",
    "How do I submit an expense claim?",
    "What is the remote work policy?",
    "How do I access my payslip?",
    "What training opportunities are available?",
    "How do I refer a candidate?",
    "What is the bereavement leave policy?",
    "How do I update my personal information?",
    "What is the company dress code?",
    "How do I request flexible working?",
    "What are the probation period terms?",
    "How do I raise a grievance?",
    "What is the annual leave policy?",
    "How do I book a meeting room?",
    "What wellness programs are offered?",
    "How do I access employee assistance?",
    "What is the performance review process?",
    "How do I request parental leave?",
    "What equipment can I request?",
    "How do I change my emergency contact?",
    "What happens during a return-to-work interview?",
]


@dataclass
class AuthContext:
    status: Literal["unauthenticated", "loading", "denied", "authenticated"]
    email: Optional[str] = None
    role: Optional[str] = None


def _inject_theme_css() -> None:
    """Inject shared UI stylesheet."""
    css_cache_key = "_inara_theme_css"
    css_markup: Optional[str] = st.session_state.get(css_cache_key)
    if css_markup is None:
        try:
            css_text = THEME_CSS_PATH.read_text()
            css_markup = f"<style>{css_text}</style>"
            st.session_state[css_cache_key] = css_markup
        except FileNotFoundError:
            logging.warning("Theme CSS not found at %s", THEME_CSS_PATH)
            return
    st.markdown(css_markup, unsafe_allow_html=True)


def _resolve_auth_context() -> AuthContext:
    """Resolve current authentication status from Streamlit identity."""
    auth_pending = bool(st.session_state.get("_auth_pending"))
    stored_email = st.session_state.get("logged_in_email")
    if stored_email:
        role = _derive_role(stored_email)
        if role == "unauthorized":
            st.session_state.pop("logged_in_email", None)
            st.session_state["_auth_pending"] = False
            return AuthContext(status="denied", email=stored_email, role=role)
        st.session_state["_auth_pending"] = False
        return AuthContext(status="authenticated", email=stored_email, role=role)

    resolved_email = _get_current_email()
    if resolved_email:
        role = _derive_role(resolved_email)
        if role == "unauthorized":
            st.session_state["_auth_pending"] = False
            return AuthContext(status="denied", email=resolved_email, role=role)
        st.session_state["logged_in_email"] = resolved_email
        st.session_state["_auth_pending"] = False
        return AuthContext(status="authenticated", email=resolved_email, role=role)

    user_obj = getattr(st, "user", None)
    if auth_pending and user_obj:
        return AuthContext(status="loading")

    st.session_state.pop("_auth_pending", None)
    return AuthContext(status="unauthenticated")


def render_login_screen() -> None:
    """Render hero-style Google login screen."""
    st.markdown("<div class='inara-auth-container'><div class='inara-auth-card'>", unsafe_allow_html=True)
    col_brand, col_action = st.columns([1.35, 1])
    with col_brand:
        st.markdown(
            """
            <div class="inara-brand-block">
                <div class="inara-auth-chip">Google Workspace · SSO enforced</div>
                <h1>Inara HR Assistant</h1>
                <p>
                    One secure gateway for policies, benefits, and people workflows. Stay aligned with
                    executive-only briefings while giving every employee the clarity they need.
                </p>
                <ul class="inara-auth-perks">
                    <li>Enterprise-grade access control</li>
                    <li>Executive and employee briefings in one place</li>
                    <li>Live HR knowledge updated from S3</li>
                </ul>
                <div class="inara-auth-meta">
                    <span>24/7 Copilot coverage</span>
                    <span>Backed by secure audit trails</span>
                    <span>Internal-only documents</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_action:
        st.markdown("<div class='inara-action-block'>", unsafe_allow_html=True)
        st.markdown(
            """
            <div class="inara-action-header">
                <h3>Sign in to continue</h3>
                <p>Use your corporate Google identity. No personal accounts are allowed.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Sign in with Google", key="auth_google", use_container_width=True):
            try:
                st.session_state["_auth_pending"] = True
                st.login("google")
            except Exception:
                st.session_state["_auth_pending"] = True
                st.login()
        st.markdown(
            f"""<div class='inara-support-link'>Need help signing in? <a href='mailto:{SUPPORT_CONTACT_EMAIL}'>Contact support</a></div>""",
            unsafe_allow_html=True,
        )
        allow_dev = os.getenv("ALLOW_DEV_LOGIN", "false").lower() in ("1", "true", "yes")
        if allow_dev:
            dev_email = st.text_input(
                "Developer email (local testing)",
                value=os.getenv("DEV_TEST_EMAIL", ""),
                placeholder="dev@company.com",
            )
            if st.button("Dev sign-in", key="dev_login", use_container_width=True) and dev_email:
                st.session_state["logged_in_email"] = dev_email.strip().lower()
                st.session_state["_auth_pending"] = False
                _rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div></div>", unsafe_allow_html=True)


def render_auth_loading(message: str = "Verifying your session...") -> None:
    st.markdown(
        f"""
        <div class='inara-auth-container'>
            <div class='inara-auth-card'>
                <div class='inara-brand-block'>
                    <h1>Hold on a moment</h1>
                    <p>{message}</p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_access_denied(email: str | None) -> None:
    st.markdown(
        f"""
        <div class='inara-auth-container'>
            <div class='inara-auth-card'>
                <div class='inara-error-card'>
                    <h3>Access denied</h3>
                    <p>Access denied for <strong>{email or 'this account'}</strong>. Only authorized company emails can use Inara.</p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col_retry, col_support = st.columns([1, 1])
    with col_retry:
        if st.button("Try a different account", use_container_width=True):
            st.session_state.pop("logged_in_email", None)
            st.session_state.pop("_auth_pending", None)
            try:
                st.logout()
            except Exception:
                _clear_query_params()
            _rerun()
    with col_support:
        st.link_button("Contact support", f"mailto:{SUPPORT_CONTACT_EMAIL}", use_container_width=True)


def render_dashboard_header(user_name: str, role: str) -> None:
    st.markdown(
        f"""
        <div class='inara-role-banner'>
            <div>
                <div style="font-size:1.2rem;font-weight:600;">Welcome back, {user_name}</div>
                <div style="color:var(--text-secondary);">How can Inara help you today?</div>
            </div>
            <div class='inara-role-badge'>{role.title()} Access</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================================
# MINIMAL PROFESSIONAL STYLING 
# ============================================================================


# ============================================================================
# RESOURCE LOADING & CACHING
# ============================================================================


@st.cache_resource(show_spinner=False)
def load_bot(user_role: str = "employee") -> HrBot:
    """Load bot instance with role-based S3 document access."""
    return HrBot(user_role=user_role, use_s3=True)


@st.cache_resource(show_spinner=False)
def get_executor() -> ThreadPoolExecutor:
    """Get thread pool executor."""
    return ThreadPoolExecutor(max_workers=2)


# ============================================================================
# CONTENT FORMATTING
# ============================================================================


def format_sources(answer: str) -> str:
    """Format source citations cleanly."""
    lines = answer.splitlines()
    if not lines:
        return answer

    for idx, line in enumerate(lines):
        if line.lower().startswith("sources:"):
            # Extract sources after "Sources:" - handle both comma and bullet separators
            sources_text = line.split(":", 1)[1].strip()
            
            # CRITICAL FIX: Remove leading bullet if present (agent sometimes adds it incorrectly)
            if sources_text.startswith("-") or sources_text.startswith("\u2022"):
                sources_text = sources_text[1:].strip()
            
            # Split by bullet placeholders or comma
            bullet_separator = " - "
            if "\u2022" in sources_text:
                bullet_separator = " \u2022 "
            if bullet_separator.strip() and bullet_separator in sources_text:
                parts = [p.strip() for p in sources_text.split(bullet_separator) if p.strip()]
            else:
                parts = [p.strip() for p in sources_text.split(",") if p.strip()]
            
            source_items: List[str] = []

            for part in parts:
                # Clean up the source name (remove extra spaces, prefixes)
                file_name = part.strip()
                
                # Remove any leading numbering like "[1]" or "1."
                import re
                file_name = re.sub(r'^\[\d+\]\s*', '', file_name)
                file_name = re.sub(r'^\d+\.\s*', '', file_name)
                
                if not file_name:
                    continue

                # Keep the .docx extension for accuracy, just format nicely
                display_name = file_name.replace("_", " ")
                source_items.append(f"`{display_name}`")

            if source_items:
                separator = " · ".join(source_items)
                lines[idx] = f"\n\n---\n\n**Sources:** {separator}"
            else:
                lines[idx] = ""
            break

    return "\n".join(lines)


def clean_markdown_artifacts(text: str) -> str:
    """Remove markdown code block markers and other artifacts."""
    # Remove markdown code block markers
    text = text.replace("```markdown", "").replace("```", "")
    # Remove extra blank lines at start/end
    text = text.strip()
    return text


def remove_document_evidence_section(text: str) -> str:
    """CRITICAL: Remove only 'Document Evidence' section, preserve sources."""
    lines = text.splitlines()
    result_lines = []
    in_document_evidence = False
    
    for line in lines:
        # Check if we hit a "Document Evidence" section heading
        if "document evidence" in line.lower() and ("##" in line or "**" in line):
            in_document_evidence = True
            continue  # Skip the heading line
        
        # If we're in Document Evidence section, skip until we hit sources or end
        if in_document_evidence:
            # Stop skipping when we hit sources or another major section
            if (line.lower().startswith("sources:") or 
                "**sources:**" in line.lower() or
                (line.startswith("##") and "document evidence" not in line.lower())):
                in_document_evidence = False
                result_lines.append(line)  # Keep this line
            # Otherwise skip (we're still in Document Evidence section)
            continue
        
        # Keep all other lines (including sources and source documents)
        result_lines.append(line)
    
    return "\n".join(result_lines)


def format_answer(answer: str) -> str:
    """Apply formatting and clean up artifacts."""
    answer = clean_markdown_artifacts(answer)
    answer = remove_document_evidence_section(answer)  # CRITICAL: Remove Document Evidence
    answer = format_sources(answer)
    return answer


def render_message(role: str, content: str, message_id: int | None = None) -> None:
    """Render chat message with clean, professional styling and feedback buttons."""
    if role == "assistant":
        # Use st.html() for feedback controls to force pure HTML rendering
        st.markdown(
            f"""
            <div class="assistant-message-container">
                <div class="assistant-content">
                    {format_answer(content)}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.html(f"""
            <style>
                .feedback-container {{
                    display: flex;
                    align-items: center;
                    gap: 0.75rem;
                    padding: 0.75rem 0;
                    margin-top: 0.5rem;
                }}
                .feedback-label {{
                    font-size: 0.875rem;
                    color: #b8b8b8;
                    font-weight: 400;
                    margin-right: 0.25rem;
                }}
                .fb-radio {{ display: none; }}
                .feedback-btn {{
                    width: 38px;
                    height: 38px;
                    border-radius: 10px;
                    background: linear-gradient(135deg, rgba(26, 26, 46, 0.4) 0%, rgba(15, 15, 30, 0.5) 100%);
                    border: 1px solid rgba(120, 119, 198, 0.2);
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                    font-size: 20px;
                }}
                .feedback-btn:hover {{
                    transform: translateY(-2px) scale(1.08);
                    border-color: rgba(120, 119, 198, 0.4);
                    box-shadow: 0 4px 12px rgba(120, 119, 198, 0.15);
                }}
                .fb-radio:checked + .feedback-btn {{
                    transform: scale(1.15);
                    transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
                }}
                .fb-radio:checked + .thumbs-up {{
                    background: linear-gradient(135deg, rgba(76, 175, 80, 0.5) 0%, rgba(56, 142, 60, 0.6) 100%);
                    border-color: rgba(76, 175, 80, 0.9);
                    box-shadow: 0 0 30px rgba(76, 175, 80, 0.7), 0 8px 25px rgba(0, 0, 0, 0.3);
                }}
                .fb-radio:checked + .thumbs-down {{
                    background: linear-gradient(135deg, rgba(244, 67, 54, 0.5) 0%, rgba(211, 47, 47, 0.6) 100%);
                    border-color: rgba(244, 67, 54, 0.9);
                    box-shadow: 0 0 30px rgba(244, 67, 54, 0.7), 0 8px 25px rgba(0, 0, 0, 0.3);
                }}
            </style>
            <div class="feedback-container">
                <span class="feedback-label">Was this helpful?</span>

                <input type="radio" name="fb-{message_id}" id="fb-{message_id}-up" class="fb-radio" />
                <label for="fb-{message_id}-up" class="feedback-btn thumbs-up" title="Helpful">&#10003;</label>

                <input type="radio" name="fb-{message_id}" id="fb-{message_id}-down" class="fb-radio" />
                <label for="fb-{message_id}-down" class="feedback-btn thumbs-down" title="Not helpful">&#10005;</label>
            </div>
        """)
    else:
        st.markdown(f'<div class="user-message">{content}</div>', unsafe_allow_html=True)


# ============================================================================
# BACKGROUND PROCESSING
# ============================================================================


def _warm_bot(bot: HrBot) -> None:
    """Warm up the bot."""
    try:
        hybrid_tool = getattr(bot, "hybrid_rag_tool", None)
        retriever = getattr(hybrid_tool, "retriever", None) if hybrid_tool else None
        if retriever:
            retriever.build_index(force_rebuild=False)
            for query in WARMUP_QUERIES:
                try:
                    retriever.hybrid_search(query, top_k=3)
                except Exception:
                    continue
        bot.crew()
    except Exception:
        pass


def build_history_context(history: List[Dict[str, str]], new_question: str | None = None, max_turns: int = 3) -> str:
    """
    Construct conversation context with BOTH user questions AND assistant answers.
    CRITICAL FIX: Include assistant responses for proper followup question handling.
    
    Args:
        history: List of message dicts with 'role' and 'content'
        new_question: Current user question (not yet in history)
        max_turns: Number of recent Q&A turns to include (default: 3 = last 3 conversations)
    
    Returns:
        Formatted conversation context string
    """
    if not history and not new_question:
        return ""
    
    # Build conversation turns (Q&A pairs)
    # Take last N*2 messages (N questions + N answers)
    max_messages = max_turns * 2
    recent_history = history[-max_messages:] if len(history) > max_messages else history
    
    context_parts = []
    if recent_history:
        context_parts.append("Recent conversation:")
        
        # Format each turn with both question and answer
        for msg in recent_history:
            role = msg.get("role", "")
            content = msg.get("content", "")[:300]  # Limit to 300 chars per message
            
            if role == "user":
                context_parts.append(f"User: {content}")
            elif role == "assistant":
                # Remove sources from context to save tokens
                clean_content = content.split("Sources:")[0].strip()
                context_parts.append(f"Assistant: {clean_content}")
    
    # Add current question if provided (for followup detection)
    if new_question:
        context_parts.append(f"Current question: {new_question[:200]}")
    
    return "\n".join(context_parts) if context_parts else ""


def build_augmented_question(history: List[Dict[str, str]], question: str, max_turns: int = 2) -> str:
    """Augment current question with recent conversation context."""
    if not history:
        return question.strip()

    max_messages = max_turns * 2
    recent_history = history[-max_messages:] if len(history) > max_messages else history
    context_lines: List[str] = []

    for msg in recent_history:
        role = msg.get("role", "").lower()
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            content = content.split("Sources:")[0].strip()
            if not content:
                continue
            context_lines.append(f"Assistant previously said: {content[:400]}")
        elif role == "user":
            context_lines.append(f"User previously asked: {content[:200]}")

    if not context_lines:
        return question.strip()

    context_lines.append(f"Follow-up question: {question.strip()}")
    return "\n".join(context_lines)


def query_bot(bot: HrBot, question: str, history_context: str, augmented_question: str) -> str:
    """
    Query the bot with caching for ultra-fast responses.
    Uses the new query_with_cache method for automatic caching.
    """
    # Use the cached query method instead of direct crew kickoff
    return bot.query_with_cache(
        query=question,
        context=history_context or "",
        retrieval_query=augmented_question,
    )


def _rerun() -> None:
    """Trigger rerun."""
    rerun_fn = getattr(st, "rerun", None)
    exp_rerun_fn = getattr(st, "experimental_rerun", None)
    try:
        if callable(rerun_fn):
            rerun_fn()
        elif callable(exp_rerun_fn):
            exp_rerun_fn()
    except Exception:
        pass


def render_typing_indicator() -> None:
    """Render animated typing indicator."""
    typing_html = """
    <div style="display: flex; align-items: center; gap: 0.5rem; padding: 1rem 0;">
        <div style="display: flex; gap: 0.3rem;">
            <div class="typing-dot" style="width: 8px; height: 8px; background: #888888; border-radius: 50%;"></div>
            <div class="typing-dot" style="width: 8px; height: 8px; background: #888888; border-radius: 50%;"></div>
            <div class="typing-dot" style="width: 8px; height: 8px; background: #888888; border-radius: 50%;"></div>
        </div>
        <span style="color: #888888; font-size: 0.9rem; font-weight: 300; margin-left: 0.5rem;">Thinking...</span>
    </div>
    """
    st.markdown(typing_html, unsafe_allow_html=True)


# ============================================================================
# MAIN APPLICATION
# ============================================================================


def main() -> None:
    """Main application."""
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    _inject_theme_css()

    auth_ctx = _resolve_auth_context()
    if auth_ctx.status == "unauthenticated":
        _set_page_mode("auth")
        render_login_screen()
        return
    if auth_ctx.status == "loading":
        _set_page_mode("auth")
        render_auth_loading()
        return
    if auth_ctx.status == "denied":
        _set_page_mode("auth")
        render_access_denied(auth_ctx.email)
        return

    _set_page_mode("app")

    user_email = auth_ctx.email or "unknown"
    user_role = auth_ctx.role or "employee"
    user_obj = getattr(st, "user", None)
    user_name = (
        getattr(user_obj, "name", None)
        or (user_email.split("@")[0] if "@" in user_email else user_email)
    )

    if os.getenv("DEBUG_AUTH", "false").lower() in ("1", "true", "yes"):
        st.sidebar.markdown("### Debug: Streamlit user")
        try:
            st.sidebar.json(dict(st.user))  # type: ignore[arg-type]
        except Exception:
            st.sidebar.write(getattr(st, "user", None))

    render_dashboard_header(user_name, user_role)
    st.caption(
        "Your intelligent HR companion for policies, benefits, and workplace guidance -- available 24/7"
    )
    if st.button("Sign out", key="logout_btn"):
        for key in ["dev_email", "logged_in_email", "_pkce_verifier", "_oauth_state", "_auth_pending"]:
            st.session_state.pop(key, None)
        try:
            st.logout()
        except Exception:
            _clear_query_params()
        _rerun()

    # Inject simple, reliable feedback interaction
    st.markdown(
        """
        <script>
        (function () {
            if (window.__hrbotFeedbackInitialized) {
                return;
            }
            window.__hrbotFeedbackInitialized = true;

            document.addEventListener('click', (event) => {
                const button = event.target.closest('.feedback-btn');
                if (!button) {
                    return;
                }

                const container = button.closest('.feedback-container');
                if (container) {
                    // Remove selection from all buttons in this container
                    container.querySelectorAll('.feedback-btn').forEach((btn) => {
                        btn.classList.remove('selected');
                    });
                }

                // Add selected class - CSS will handle the visual effect
                button.classList.add('selected');

                const messageId = button.getAttribute('data-message-id');
                const sentiment = button.getAttribute('data-feedback');
                console.log(`Feedback recorded: message ${messageId} = ${sentiment}`);
            });
            
            console.log('Feedback system ready');
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )
    # Initialize session state
    if "history" not in st.session_state:
        st.session_state["history"] = []
    if "pending_response" not in st.session_state:
        st.session_state["pending_response"] = None
    if "warm_future" not in st.session_state:
        st.session_state["warm_future"] = None
    if "cache_cleared_msg" not in st.session_state:
        st.session_state["cache_cleared_msg"] = None
    if "s3_refresh_msg" not in st.session_state:
        st.session_state["s3_refresh_msg"] = None

    # Load resources with role-based access
    with st.spinner(f"Initializing {user_role.title()} HR Assistant..."):
        try:
            bot = load_bot(user_role=user_role)
            st.success(f"{user_role.title()} HR Assistant loaded successfully.")
        except Exception as e:
            st.error(f"Failed to load HR Assistant: {e}")
            st.error("Please try refreshing the page or contact support.")
            st.stop()

    executor = get_executor()

    def submit_question(prompt: str) -> None:
        history_context = build_history_context(st.session_state["history"], prompt)
        augmented_question = build_augmented_question(st.session_state["history"], prompt)
        st.session_state["history"].append({"role": "user", "content": prompt})
        future = executor.submit(query_bot, bot, prompt, history_context, augmented_question)
        st.session_state["pending_response"] = {"future": future, "start_time": time.time()}
        _rerun()
    
    # ============================================================================
    # ACTION BUTTONS - Professional side-by-side layout
    # ============================================================================
    action_buttons = st.container()
    with action_buttons:
        st.markdown('<div class="action-buttons-container">', unsafe_allow_html=True)
        
        # Create two columns for side-by-side buttons
        col1, col2 = st.columns(2, gap="medium")
        
        # S3 Refresh Button (Blue - Left)
        with col1:
            st.markdown('<div class="s3-refresh-container">', unsafe_allow_html=True)
            if st.button("Refresh S3 Docs", key="s3_refresh_btn", help="Download the latest HR policy documents from S3. Use this when new policies are uploaded.", use_container_width=True):
                try:
                    from hr_bot.utils.s3_loader import S3DocumentLoader
                    from hr_bot.crew import HrBot
                    import shutil
                    from pathlib import Path
                    
                    # Initialize S3 loader and force refresh
                    s3_loader = S3DocumentLoader(user_role=user_role)
                    s3_loader.clear_cache()
                    document_paths = s3_loader.load_documents(force_refresh=True)
                    
                    # CRITICAL FIX #1: Delete FAISS/BM25 index files on disk
                    rag_index_dir = Path(".rag_index")
                    if rag_index_dir.exists():
                        shutil.rmtree(rag_index_dir)
                        print("Deleted .rag_index directory")
                    
                    # CRITICAL FIX #2: Clear in-memory RAG tool cache
                    HrBot.clear_rag_cache()
                    
                    # CRITICAL FIX #3: Clear Streamlit resource cache (bot instance)
                    load_bot.clear()
                    print("Cleared Streamlit resource cache")
                    
                    # Clear session state bot instance
                    if 'bot_instance' in st.session_state:
                        del st.session_state['bot_instance']
                    
                    st.session_state["s3_refresh_msg"] = f"Refreshed {len(document_paths)} HR documents from S3 and rebuilt RAG indexes."
                    _rerun()
                except Exception as e:
                    st.session_state["s3_refresh_msg"] = f"Error refreshing S3 documents: {e}"
                    _rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Clear Cache Button (Red - Right)
        with col2:
            st.markdown('<div class="clear-cache-container">', unsafe_allow_html=True)
            if st.button("Clear Response Cache", key="clear_cache_btn", help="Clear cached responses. Use this if you get a technical error and want to retry your query.", use_container_width=True):
                try:
                    bot.response_cache.clear_all()
                    st.session_state["cache_cleared_msg"] = "Response cache cleared successfully. You can now retry your query."
                    _rerun()
                except Exception as e:
                    st.session_state["cache_cleared_msg"] = f"Error clearing cache: {e}"
                    _rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Show status messages if present
    if st.session_state.get("cache_cleared_msg"):
        st.success(st.session_state["cache_cleared_msg"])
        st.session_state["cache_cleared_msg"] = None
    
    if st.session_state.get("s3_refresh_msg"):
        st.success(st.session_state["s3_refresh_msg"])
        st.session_state["s3_refresh_msg"] = None

    # Background warmup
    if st.session_state["warm_future"] is None:
        st.session_state["warm_future"] = executor.submit(_warm_bot, bot)

    # Render chat history
    for idx, message in enumerate(st.session_state["history"]):
        render_message(message["role"], message["content"], message_id=idx)

    # Check pending response and show status
    pending = st.session_state.get("pending_response")
    if pending:
        future = pending["future"]
        if future.done():
            try:
                answer = future.result()
                formatted = format_answer(answer)
                st.session_state["history"].append({"role": "assistant", "content": formatted})
                del st.session_state["pending_response"]
                _rerun()
            except Exception as e:
                st.error(f"Technical error: {e}")
                st.warning("This response was cached. Clear the response cache before retrying the same question.")
                del st.session_state["pending_response"]
                _rerun()
        else:
            # Show professional animated thinking indicator while processing
            elapsed = time.time() - pending.get("start_time", time.time())
            if elapsed < 8:
                status = "Analyzing your request..."
                progress_width = "25%"
            elif elapsed < 15:
                status = "Searching policy documents..."
                progress_width = "60%"
            else:
                status = "Preparing your response..."
                progress_width = "85%"

            with st.chat_message("assistant"):
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, rgba(26, 26, 46, 0.95) 0%, rgba(15, 15, 30, 0.98) 100%); border: 1px solid rgba(120, 119, 198, 0.2); border-radius: 16px; padding: 2rem; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);">
                    <div style="display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem;">
                        <div style="width: 40px; height: 40px; background: linear-gradient(135deg, #7877c6 0%, #9b8fd9 100%); border-radius: 10px; display: flex; align-items: center; justify-content: center; animation: pulse 2s ease-in-out infinite; box-shadow: 0 4px 12px rgba(120, 119, 198, 0.4);">
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <circle cx="12" cy="12" r="10" stroke="white" stroke-width="2" fill="none" opacity="0.8"/>
                                <path d="M12 6v6l4 2" stroke="white" stroke-width="2" stroke-linecap="round" opacity="0.9"/>
                            </svg>
                        </div>
                        <div style="flex: 1;">
                            <div style="color: #e8e8e8; font-size: 1rem; font-weight: 500; margin-bottom: 0.5rem;">
                                {status}
                            </div>
                            <div style="width: 100%; height: 4px; background: rgba(255, 255, 255, 0.1); border-radius: 2px; overflow: hidden;">
                                <div style="width: {progress_width}; height: 100%; background: linear-gradient(90deg, #7877c6 0%, #9b8fd9 100%); border-radius: 2px; transition: width 0.3s ease; box-shadow: 0 0 10px rgba(120, 119, 198, 0.5);"></div>
                            </div>
                        </div>
                    </div>
                    <div style="display: flex; gap: 0.4rem; justify-content: center;">
                        <div class="typing-dot" style="width: 8px; height: 8px; background: rgba(120, 119, 198, 0.6); border-radius: 50%;"></div>
                        <div class="typing-dot" style="width: 8px; height: 8px; background: rgba(120, 119, 198, 0.6); border-radius: 50%;"></div>
                        <div class="typing-dot" style="width: 8px; height: 8px; background: rgba(120, 119, 198, 0.6); border-radius: 50%;"></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            time.sleep(1)
            _rerun()

    # Chat input - add to history and process asynchronously
    if prompt := st.chat_input(DEFAULT_PLACEHOLDER):
        submit_question(prompt)


if __name__ == "__main__":
    main()
