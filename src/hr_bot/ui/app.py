"""
Inara - Your HR Assistant
Professional Enterprise UI - Clean, modern interface for HR policy assistance
"""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional
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


# Custom in-app PKCE OAuth removed — use Streamlit built-in `st.login()` / `st.user` only.

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

def ensure_authenticated() -> bool:
    """Check authentication using Streamlit's built-in OAuth."""
    # If we already have a logged in email from an earlier OAuth flow, use it
    if st.session_state.get("logged_in_email"):
        # Short-circuit: derive role from persisted email
        user_email = st.session_state.get("logged_in_email")
        # Validate persisted email before using it
        if not user_email or '@' not in str(user_email):
            # Clear any invalid persisted login and prompt the user to sign in again
            try:
                st.session_state.pop('logged_in_email', None)
            except Exception:
                pass
            st.info("We couldn't read your previous login. Please sign in with Google to continue.")
            return False
        # Optional debug (controlled by env flag)
        if os.getenv("DEBUG_AUTH", "false").lower() in ("1", "true", "yes"):
            st.sidebar.write("DEBUG st.user:", getattr(st, "user", None))
            try:
                if getattr(st, 'user', None):
                    try:
                        st.sidebar.json(dict(st.user))
                    except Exception:
                        pass
            except Exception:
                pass

        st.sidebar.markdown("### Debug: User Info")
        st.sidebar.markdown(f"**Extracted Email:** {user_email}")
        user_role = _derive_role(user_email)
        if user_role == 'unauthorized':
            st.error(f"Access denied for {user_email}. Please contact your administrator.")
            st.sidebar.markdown(f"**Role:** {user_role}")
            return False
        st.sidebar.markdown(f"**Role:** {user_role}")
        return True

    # Rely on Streamlit's built-in `st.login()` / `st.user` identity cookie.
    # The Streamlit runtime will populate `st.user` after a successful
    # `st.login()` flow; we do not perform manual code exchanges here.

    # Developer auto-login (local testing convenience)
    allow_dev_env = os.getenv("ALLOW_DEV_LOGIN", "false").lower() in ("1", "true", "yes")
    dev_email_env = os.getenv("DEV_TEST_EMAIL", "").strip().lower()
    # Try to extract any email-like attribute from Streamlit's `st.user` object
    st_user_email = None
    try:
        if getattr(st, 'user', None):
            # Follow required extraction order here as a quick-guess (dropped validation will occur later)
            try:
                if hasattr(st.user, 'email') and st.user.email:
                    st_user_email = str(st.user.email).strip().lower()
                elif hasattr(st.user, 'preferred_username') and st.user.preferred_username:
                    st_user_email = str(st.user.preferred_username).strip().lower()
                elif hasattr(st.user, 'name') and st.user.name and '@' in str(st.user.name):
                    st_user_email = str(st.user.name).strip().lower()
                elif hasattr(st.user, 'sub') and st.user.sub and '@' in str(st.user.sub):
                    st_user_email = str(st.user.sub).strip().lower()
            except Exception:
                st_user_email = None
    except Exception:
        st_user_email = None

    if allow_dev_env and dev_email_env and not st.session_state.get("logged_in_email") and not st_user_email:
        # Auto-populate the session for local developer testing to avoid 'unknown' access
        st.session_state["dev_email"] = dev_email_env
        st.session_state["logged_in_email"] = dev_email_env
        st.sidebar.markdown("**Developer auto-login enabled (from DEV_TEST_EMAIL)**")
        return True

    # If user is not logged in, show login button / OAuth option
        if not st.user:
                # Polished login card: centered, clear title, short description, and supportive note
                st.markdown(
                        """
                        <style>
                        .login-card{display:flex;align-items:center;justify-content:center;margin-top:2.5rem;padding:0 1rem}
                        .login-inner{background:linear-gradient(180deg,#ffffff, #fbfbff);box-shadow:0 10px 40px rgba(30,30,60,0.08);border-radius:14px;padding:40px;max-width:740px;width:100%;}
                        .brand-row{display:flex;align-items:center;gap:16px;margin-bottom:8px}
                        .brand-title{font-size:34px;font-weight:800;margin:0;background:linear-gradient(90deg,#2b2f7a,#6f6fe8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
                        .brand-sub{color:#6b6b80;margin-top:6px;margin-bottom:20px}
                        .login-actions{display:flex;align-items:center;justify-content:center;gap:12px;margin-top:18px}
                        .legal-note{color:#9aa0b4;font-size:12px;margin-top:12px;text-align:center}
                        /* Google-like button styling for Streamlit buttons */
                        .stButton>button{background:#fff;border:1px solid #dcdfe6;color:#202124;padding:10px 14px;border-radius:10px;display:inline-flex;align-items:center;gap:10px;box-shadow:none;font-weight:600}
                        .stButton>button:hover{box-shadow:0 2px 6px rgba(60,64,67,0.08)}
                        .stButton>button:active{transform:translateY(1px)}
                        /* Add left padding to visually reserve space for an icon */
                        .stButton>button{padding-left:48px}
                        /* Decorative pseudo-icon using radial-gradient to mimic multicolor mark */
                        .stButton>button::before{content:'';width:20px;height:20px;border-radius:4px;margin-left:-36px;margin-right:12px;display:inline-block;background-image:linear-gradient(45deg,#4285F4 0%,#34A853 50%,#FBBC05 75%,#EA4335 100%)}
                        @media (max-width:520px){.login-inner{padding:22px}.brand-title{font-size:22px}}
                        /* entrance animation */
                        @keyframes liftFade {
                            0% {opacity:0; transform: translateY(14px) scale(0.995)}
                            100% {opacity:1; transform: translateY(0) scale(1)}
                        }
                        .login-inner{animation: liftFade 420ms cubic-bezier(.2,.9,.2,1) both}
                        .privacy-link{color:#6b6b80;font-size:13px;text-decoration:none;border-bottom:1px dotted rgba(107,107,128,0.25);padding-bottom:2px}
                        </style>

                        <div class="login-card">
                            <div class="login-inner">
                                <div class="brand-row" style="justify-content:center;">
                                    <div>
                                        <div class="brand-title">Inara</div>
                                        <div class="brand-sub">HR Assistant — Secure access to company policies and documents.</div>
                                    </div>
                                </div>
                                <div style="color:#333333;font-size:15px;line-height:1.45;text-align:center">
                                    Sign in with your company Google account to continue. Access is restricted to authorized employees only.
                                </div>
                                <div class="login-actions">
                                    <!-- placeholder for Streamlit buttons; real interactive buttons render below -->
                                </div>
                                <div class="legal-note">By signing in you agree to your company's acceptable use policy. Your login is securely handled by Google.</div>
                            </div>
                        </div>
                        <div style="text-align:center;margin-top:12px">
                            <a class="privacy-link" href="#" target="_blank">Privacy &amp; Policies</a>
                        </div>
                        """,
                        unsafe_allow_html=True,
                )
        # Prefer Streamlit's built-in OIDC when configured via .streamlit/secrets.toml
        try:
            auth_section = None
            try:
                auth_section = st.secrets.get("auth") if hasattr(st, "secrets") else None
            except Exception:
                auth_section = None

            if auth_section:
                # If a provider named 'google' is configured, show a dedicated button
                providers = []
                try:
                    providers = list(auth_section.keys())
                except Exception:
                    providers = []

                if "google" in providers:
                    # Center the sign-in button under the card for a cleaner look
                    left, mid, right = st.columns([1, 2, 1])
                    with mid:
                        if st.button("Sign in with Google"):
                            try:
                                st.login("google")
                            except Exception:
                                try:
                                    st.login()
                                except Exception:
                                    pass

                    return False
                else:
                    # Generic built-in login (first provider)
                    try:
                        st.login()
                        return False
                    except Exception:
                        # fall through to developer fallback if st.login isn't available
                        pass

            # No Streamlit built-in provider configured: offer developer fallback only
            allow_dev = os.getenv("ALLOW_DEV_LOGIN", "false").lower() in ("1", "true", "yes")
            if allow_dev:
                st.warning("Developer fallback enabled. Only use this locally.")
                dev_email = st.text_input("Developer email (for local testing)", value=os.getenv("DEV_TEST_EMAIL", ""))
                # Keep developer button centered as well
                l, m, r = st.columns([1, 2, 1])
                with m:
                    if st.button("Sign in (dev)") and dev_email:
                        st.session_state["dev_email"] = dev_email.strip().lower()
                        st.session_state["logged_in_email"] = dev_email.strip().lower()
                        return True
            else:
                st.info("Sign in is not available in this environment. Configure Streamlit OIDC via `.streamlit/secrets.toml`.")

            return False
        except Exception:
            # Fallback: developer login
            allow_dev = os.getenv("ALLOW_DEV_LOGIN", "false").lower() in ("1", "true", "yes")
            if allow_dev:
                st.warning("Developer fallback enabled. Only use this locally.")
                dev_email = st.text_input("Developer email (for local testing)", value=os.getenv("DEV_TEST_EMAIL", ""))
                if st.button("Sign in (dev)") and dev_email:
                    st.session_state["dev_email"] = dev_email.strip().lower()
                    st.session_state["logged_in_email"] = dev_email.strip().lower()
                    return True
            else:
                st.info("Sign in is not available in this environment. Configure Streamlit OIDC or enable developer login.")

            return False

    # User is authenticated, check RBAC
    # Optional debug sidebar controlled by env var
    if os.getenv("DEBUG_AUTH", "false").lower() in ("1", "true", "yes"):
        st.sidebar.write("DEBUG st.user:", getattr(st, "user", None))
        if getattr(st, 'user', None):
            try:
                st.sidebar.json(dict(st.user))
            except Exception:
                pass

    # Extract email from session / st.user / env (safe)
    user_email = _get_current_email()

    # If st.user exists but we couldn't determine a usable email, show clear message and
    # offer a retry using Streamlit's login so the user can re-run the provider flow.
    if getattr(st, 'user', None) and (not user_email or '@' not in user_email):
        # Friendly non-blocking message and clear CTA to re-run the provider flow
        try:
            st.session_state.pop('logged_in_email', None)
        except Exception:
            pass
        st.info("Please complete sign-in with Google so we can verify your company account.")
        # Offer a retry button to trigger the provider login again (safe no-op if not configured)
        try:
            col_a, col_b = st.columns([1, 1])
            with col_a:
                if st.button("Sign in with Google"):
                    try:
                        st.login("google")
                    except Exception:
                        try:
                            st.login()
                        except Exception:
                            pass
            with col_b:
                # Provide developer fallback option if enabled
                if os.getenv("ALLOW_DEV_LOGIN", "false").lower() in ("1", "true", "yes"):
                    if st.button("Use developer login"):
                        dev_email = os.getenv("DEV_TEST_EMAIL", "")
                        if dev_email:
                            st.session_state['dev_email'] = dev_email.strip().lower()
                            st.session_state['logged_in_email'] = dev_email.strip().lower()
                            st.experimental_rerun()
        except Exception:
            pass
        return False

    # Persist the extracted email into session state for later short-circuiting
    try:
        if user_email and not st.session_state.get('logged_in_email'):
            st.session_state['logged_in_email'] = user_email
    except Exception:
        pass

    # Before deriving roles, validate extracted email
    if not user_email or '@' not in user_email:
        # If we still don't have an email, show a friendly prompt instead of a red error
        st.info("We couldn't determine your login email. Please sign in to continue.")
        return False

    # Now derive role and enforce RBAC
    user_role = _derive_role(user_email)
    if user_role == 'unauthorized':
        st.error(f"Access denied for {user_email}. Please contact your administrator.")
        st.sidebar.markdown(f"**Role:** {user_role}")
        return False

    st.sidebar.markdown(f"**Extracted Email:** {user_email}")
    st.sidebar.markdown(f"**Role:** {user_role}")
    return True

# ============================================================================
# CONFIGURATION
# ============================================================================

PAGE_TITLE = "Inara - HR Assistant"
PAGE_ICON = "💼"
DATA_DIR = Path("data").resolve()
DEFAULT_PLACEHOLDER = "Ask me anything about HR policies, benefits, or procedures..."

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

# ============================================================================
# MINIMAL PROFESSIONAL STYLING 
# ============================================================================

MINIMAL_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    /* ==================== THEME TOGGLE BUTTON - ELEGANT & FIXED ==================== */
    .theme-toggle-container {
        position: fixed;
        top: 1.5rem;
        right: 2rem;
        z-index: 9999;
        animation: fadeIn 0.6s ease-out 0.4s both;
    }
    
    .theme-toggle {
        width: 48px;
        height: 48px;
        border-radius: 12px;
        background: linear-gradient(135deg, rgba(120, 119, 198, 0.15) 0%, rgba(155, 143, 217, 0.1) 100%);
        border: 1.5px solid rgba(120, 119, 198, 0.4);
        backdrop-filter: blur(12px);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: 0 4px 16px rgba(120, 119, 198, 0.15), 0 2px 4px rgba(0, 0, 0, 0.1);
        padding: 0;
        outline: none;
    }
    
    .theme-toggle:hover {
        transform: translateY(-2px) scale(1.05);
        border-color: rgba(120, 119, 198, 0.6);
        background: linear-gradient(135deg, rgba(120, 119, 198, 0.25) 0%, rgba(155, 143, 217, 0.2) 100%);
        box-shadow: 0 8px 28px rgba(120, 119, 198, 0.3), 0 4px 8px rgba(0, 0, 0, 0.15);
    }
    
    .theme-toggle:active {
        transform: translateY(0) scale(0.98);
    }
    
    .theme-toggle span {
        font-size: 22px;
        filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.2));
        transition: all 0.3s ease;
    }
    
    .light-theme .theme-toggle {
        background: linear-gradient(135deg, rgba(120, 119, 198, 0.12) 0%, rgba(155, 143, 217, 0.08) 100%);
        border: 1.5px solid rgba(120, 119, 198, 0.3);
        box-shadow: 0 4px 16px rgba(120, 119, 198, 0.12), 0 2px 4px rgba(0, 0, 0, 0.05);
    }
    
    .light-theme .theme-toggle:hover {
        background: linear-gradient(135deg, rgba(120, 119, 198, 0.2) 0%, rgba(155, 143, 217, 0.15) 100%);
        box-shadow: 0 8px 28px rgba(120, 119, 198, 0.2), 0 4px 8px rgba(0, 0, 0, 0.08);
    }
    
    /* ==================== CLEAR CACHE BUTTON - ELEGANT STYLING ==================== */
    .clear-cache-container button {
        all: unset;
        height: 48px;
        padding: 0 1.5rem;
        border-radius: 12px;
        background: linear-gradient(135deg, rgba(231, 76, 60, 0.15) 0%, rgba(192, 57, 43, 0.1) 100%);
        border: 1.5px solid rgba(231, 76, 60, 0.4);
        backdrop-filter: blur(12px);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: 0 4px 16px rgba(231, 76, 60, 0.15), 0 2px 4px rgba(0, 0, 0, 0.1);
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        font-size: 0.875rem;
        font-weight: 500;
        color: #e74c3c;
        letter-spacing: 0.01em;
        white-space: nowrap;
    }
    
    .clear-cache-container button:hover {
        transform: translateY(-2px) scale(1.02);
        border-color: rgba(231, 76, 60, 0.6);
        background: linear-gradient(135deg, rgba(231, 76, 60, 0.25) 0%, rgba(192, 57, 43, 0.2) 100%);
        box-shadow: 0 8px 28px rgba(231, 76, 60, 0.3), 0 4px 8px rgba(0, 0, 0, 0.15);
        color: #c0392b;
    }
    
    .clear-cache-container button:active {
        transform: translateY(0) scale(0.98);
    }
    
    .light-theme .clear-cache-container button {
        background: linear-gradient(135deg, rgba(231, 76, 60, 0.12) 0%, rgba(192, 57, 43, 0.08) 100%);
        border: 1.5px solid rgba(231, 76, 60, 0.3);
        box-shadow: 0 4px 16px rgba(231, 76, 60, 0.12), 0 2px 4px rgba(0, 0, 0, 0.05);
        color: #c0392b;
    }
    
    .light-theme .clear-cache-container button:hover {
        background: linear-gradient(135deg, rgba(231, 76, 60, 0.2) 0%, rgba(192, 57, 43, 0.15) 100%);
        box-shadow: 0 8px 28px rgba(231, 76, 60, 0.2), 0 4px 8px rgba(0, 0, 0, 0.08);
        color: #a93226;
    }
    
    /* ==================== ACTION BUTTONS CONTAINER - PROFESSIONAL LAYOUT ==================== */
    .action-buttons-container {
        position: fixed;
        top: 1.5rem;
        right: 5.5rem;
        z-index: 9999;
        display: flex;
        gap: 0.75rem;
        animation: fadeIn 0.6s ease-out 0.4s both;
    }
    
    /* ==================== S3 REFRESH BUTTON - ELEGANT STYLING ==================== */
    .s3-refresh-container button {
        all: unset;
        height: 48px;
        padding: 0 1.5rem;
        border-radius: 12px;
        background: linear-gradient(135deg, rgba(52, 152, 219, 0.15) 0%, rgba(41, 128, 185, 0.1) 100%);
        border: 1.5px solid rgba(52, 152, 219, 0.4);
        backdrop-filter: blur(12px);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        box-shadow: 0 4px 16px rgba(52, 152, 219, 0.15), 0 2px 4px rgba(0, 0, 0, 0.1);
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        font-size: 0.875rem;
        font-weight: 500;
        color: #3498db;
        letter-spacing: 0.01em;
        white-space: nowrap;
    }
    
    .s3-refresh-container button:hover {
        transform: translateY(-2px) scale(1.02);
        border-color: rgba(52, 152, 219, 0.6);
        background: linear-gradient(135deg, rgba(52, 152, 219, 0.25) 0%, rgba(41, 128, 185, 0.2) 100%);
        box-shadow: 0 8px 28px rgba(52, 152, 219, 0.3), 0 4px 8px rgba(0, 0, 0, 0.15);
        color: #2980b9;
    }
    
    .s3-refresh-container button:active {
        transform: translateY(0) scale(0.98);
    }
    
    .light-theme .s3-refresh-container button {
        background: linear-gradient(135deg, rgba(52, 152, 219, 0.12) 0%, rgba(41, 128, 185, 0.08) 100%);
        border: 1.5px solid rgba(52, 152, 219, 0.3);
        box-shadow: 0 4px 16px rgba(52, 152, 219, 0.12), 0 2px 4px rgba(0, 0, 0, 0.05);
        color: #2980b9;
    }
    
    .light-theme .s3-refresh-container button:hover {
        background: linear-gradient(135deg, rgba(52, 152, 219, 0.2) 0%, rgba(41, 128, 185, 0.15) 100%);
        box-shadow: 0 8px 28px rgba(52, 152, 219, 0.2), 0 4px 8px rgba(0, 0, 0, 0.08);
        color: #21618c;
    }
    
    /* ==================== FEEDBACK BUTTONS - ELEGANT DESIGN ==================== */
    .assistant-message-container {
        background: var(--card-bg);
        border: 1px solid var(--card-border);
        border-radius: 16px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }
    
    .assistant-content {
        color: var(--text-primary);
        line-height: 1.7;
    }
    
    .user-message {
        background: linear-gradient(135deg, rgba(120, 119, 198, 0.15) 0%, rgba(155, 143, 217, 0.1) 100%);
        border: 1px solid rgba(120, 119, 198, 0.25);
        border-radius: 16px;
        padding: 1.25rem 1.5rem;
        margin: 1rem 0;
        color: var(--text-primary);
    }
    
    .feedback-container {
        display: flex !important;
        gap: 0.75rem;
        margin-top: 1.5rem;
        padding-top: 1.25rem;
        border-top: 1px solid rgba(120, 119, 198, 0.15);
        align-items: center;
    }
    
    .feedback-label {
        font-size: 0.875rem;
        color: #b8b8b8 !important;
        font-weight: 400;
        margin-right: 0.25rem;
    }
    
    .feedback-btn {
        width: 38px !important;
        height: 38px !important;
        border-radius: 10px !important;
        background: linear-gradient(135deg, rgba(26, 26, 46, 0.4) 0%, rgba(15, 15, 30, 0.5) 100%) !important;
        border: 1px solid rgba(120, 119, 198, 0.2) !important;
        cursor: pointer !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        backdrop-filter: blur(8px);
    }
    
    .feedback-btn:hover {
        transform: translateY(-2px) scale(1.08);
        border-color: rgba(120, 119, 198, 0.4);
        box-shadow: 0 4px 12px rgba(120, 119, 198, 0.15);
    }
    
    .feedback-btn:active {
        transform: translateY(0) scale(0.95);
    }
    
    .feedback-btn.thumbs-up:hover {
        background: linear-gradient(135deg, rgba(76, 175, 80, 0.15) 0%, rgba(56, 142, 60, 0.2) 100%);
        border-color: rgba(76, 175, 80, 0.4);
    }
    
    .feedback-btn.thumbs-down:hover {
        background: linear-gradient(135deg, rgba(244, 67, 54, 0.15) 0%, rgba(211, 47, 47, 0.2) 100%);
        border-color: rgba(244, 67, 54, 0.4);
    }
    
    /* Radio-based selection (JS-free, reliable) */
    .fb-radio { display: none; }

    .fb-radio:checked + label.feedback-btn {
        transform: scale(1.15) !important;
        transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
        box-shadow: 0 8px 24px rgba(120, 119, 198, 0.25);
    }

    .fb-radio:checked + label.thumbs-up {
        background: linear-gradient(135deg, rgba(76, 175, 80, 0.5) 0%, rgba(56, 142, 60, 0.6) 100%) !important;
        border-color: rgba(76, 175, 80, 0.9) !important;
        box-shadow: 0 0 30px rgba(76, 175, 80, 0.7), 0 8px 25px rgba(0, 0, 0, 0.3) !important;
    }

    .fb-radio:checked + label.thumbs-up svg path {
        stroke: #66BB6A !important;
        opacity: 1 !important;
        stroke-width: 3 !important;
        filter: drop-shadow(0 0 10px rgba(76, 175, 80, 1));
    }

    .fb-radio:checked + label.thumbs-down {
        background: linear-gradient(135deg, rgba(244, 67, 54, 0.5) 0%, rgba(211, 47, 47, 0.6) 100%) !important;
        border-color: rgba(244, 67, 54, 0.9) !important;
        box-shadow: 0 0 30px rgba(244, 67, 54, 0.7), 0 8px 25px rgba(0, 0, 0, 0.3) !important;
    }

    .fb-radio:checked + label.thumbs-down svg path {
        stroke: #EF5350 !important;
        opacity: 1 !important;
        stroke-width: 3 !important;
        filter: drop-shadow(0 0 10px rgba(244, 67, 54, 1));
    }

    .feedback-btn.selected {
        transform: scale(1.15) !important;
        transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
    }
    
    .feedback-btn.thumbs-up.selected {
        background: linear-gradient(135deg, rgba(76, 175, 80, 0.5) 0%, rgba(56, 142, 60, 0.6) 100%) !important;
        border-color: rgba(76, 175, 80, 0.9) !important;
        box-shadow: 0 0 30px rgba(76, 175, 80, 0.7), 0 8px 25px rgba(0, 0, 0, 0.3) !important;
    }
    
    .feedback-btn.thumbs-up.selected svg path {
        stroke: #66BB6A !important;
        opacity: 1 !important;
        stroke-width: 3 !important;
        filter: drop-shadow(0 0 10px rgba(76, 175, 80, 1));
    }
    
    .feedback-btn.thumbs-down.selected {
        background: linear-gradient(135deg, rgba(244, 67, 54, 0.5) 0%, rgba(211, 47, 47, 0.6) 100%) !important;
        border-color: rgba(244, 67, 54, 0.9) !important;
        box-shadow: 0 0 30px rgba(244, 67, 54, 0.7), 0 8px 25px rgba(0, 0, 0, 0.3) !important;
    }
    
    .feedback-btn.thumbs-down.selected svg path {
        stroke: #EF5350 !important;
        opacity: 1 !important;
        stroke-width: 3 !important;
        filter: drop-shadow(0 0 10px rgba(244, 67, 54, 1));
    }
    
    .feedback-btn svg {
        transition: all 0.3s ease;
    }
    
    .feedback-btn:hover svg {
        transform: scale(1.15);
    }
    
    /* Light theme feedback buttons */
    .light-theme .feedback-btn {
        background: linear-gradient(135deg, rgba(248, 249, 250, 0.8) 0%, rgba(233, 236, 239, 0.9) 100%);
        border: 1px solid rgba(120, 119, 198, 0.15);
    }
    
    .light-theme .feedback-btn:hover {
        box-shadow: 0 4px 12px rgba(120, 119, 198, 0.1);
    }
    
    .light-theme .feedback-label {
        color: #6c757d;
    }
    
    @keyframes feedbackPulse {
        0% {
            transform: scale(1);
        }
        30% {
            transform: scale(1.2);
        }
        50% {
            transform: scale(1.15);
        }
        70% {
            transform: scale(1.18);
        }
        100% {
            transform: scale(1.05);
        }
    }
    
    /* ==================== GLOBAL RESET ==================== */
    * {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Remove edit buttons completely */
    button[title="Copy message"],
    button[title="Copy"],
    button[aria-label*="Copy"],
    [data-testid="stChatMessageCopyButton"],
    .stChatMessage button {
        display: none !important;
    }
    
    /* ==================== THEME VARIABLES ==================== */
    :root {
        --bg-gradient-start: #1a1a2e;
        --bg-gradient-mid: #0f0f1e;
        --bg-gradient-end: #000000;
        --text-primary: #e5e5e5;
        --text-secondary: #a0a0a0;
        --card-bg: rgba(26, 26, 46, 0.95);
        --card-border: rgba(120, 119, 198, 0.2);
        --accent-color: rgba(120, 119, 198, 0.5);
    }
    
    .light-theme {
        --bg-gradient-start: #f8f9fa;
        --bg-gradient-mid: #e9ecef;
        --bg-gradient-end: #dee2e6;
        --text-primary: #212529;
        --text-secondary: #6c757d;
        --card-bg: rgba(255, 255, 255, 0.95);
        --card-border: rgba(120, 119, 198, 0.15);
        --accent-color: rgba(120, 119, 198, 0.7);
    }
    
    /* ==================== DARK THEME BASE WITH RICH GRADIENT ==================== */
    .main {
        background: radial-gradient(ellipse at top, var(--bg-gradient-start) 0%, var(--bg-gradient-mid) 50%, var(--bg-gradient-end) 100%) !important;
        color: var(--text-primary);
        min-height: 100vh;
        position: relative;
        transition: background 0.4s ease, color 0.4s ease;
    }
    
    /* Subtle animated background effect */
    .main::before {
        content: '';
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: 
            radial-gradient(ellipse at 20% 30%, rgba(120, 119, 198, 0.05) 0%, transparent 50%),
            radial-gradient(ellipse at 80% 70%, rgba(255, 107, 107, 0.03) 0%, transparent 50%);
        pointer-events: none;
        z-index: 0;
    }
    
    .block-container {
        padding-top: 3rem !important;
        padding-bottom: 2rem !important;
        max-width: 900px !important;
        position: relative;
        z-index: 1;
    }
    
    /* ==================== HEADER - STUNNING GRADIENT TITLE ==================== */
    h1 {
        font-size: 2.5rem !important;
        font-weight: 700 !important;
        background: linear-gradient(135deg, #ffffff 0%, #a8a8ff 50%, #7877c6 100%) !important;
        -webkit-background-clip: text !important;
        -webkit-text-fill-color: transparent !important;
        background-clip: text !important;
        margin-bottom: 0.5rem !important;
        letter-spacing: -0.04em !important;
        animation: fadeInDown 0.6s ease-out;
    }
    
    /* Subtitle with elegant styling */
    [data-testid="stCaptionContainer"] {
        font-size: 1.05rem !important;
        color: #a0a0a0 !important;
        font-weight: 400 !important;
        margin-bottom: 2.5rem !important;
        letter-spacing: 0.02em !important;
        animation: fadeIn 0.8s ease-out 0.2s both;
    }
    
    /* ==================== CHAT MESSAGES - ELEGANT BUBBLES WITH DEPTH ==================== */
    .stChatMessage {
        background: transparent !important;
        padding: 1rem 0 !important;
        border: none !important;
        margin: 0.5rem 0 !important;
    }
    
    /* User messages - sleek, right-aligned with subtle glow */
    [data-testid="user"] {
        display: flex;
        justify-content: flex-end;
    }
    
    [data-testid="user"] > div {
        background: linear-gradient(135deg, rgba(120, 119, 198, 0.15) 0%, rgba(120, 119, 198, 0.08) 100%) !important;
        border: 1px solid rgba(120, 119, 198, 0.25) !important;
        color: #e8e8e8 !important;
        padding: 1.1rem 1.5rem !important;
        border-radius: 1.5rem 1.5rem 0.5rem 1.5rem !important;
        max-width: 75% !important;
        font-size: 0.975rem !important;
        line-height: 1.65 !important;
        box-shadow: 0 4px 12px rgba(120, 119, 198, 0.08), 0 2px 4px rgba(0, 0, 0, 0.15) !important;
        backdrop-filter: blur(8px) !important;
        transition: all 0.3s ease !important;
    }
    
    [data-testid="user"] > div:hover {
        border-color: rgba(120, 119, 198, 0.35) !important;
        box-shadow: 0 6px 16px rgba(120, 119, 198, 0.12), 0 3px 6px rgba(0, 0, 0, 0.2) !important;
        transform: translateY(-1px) !important;
    }
    
    /* Assistant messages - premium card design with gradient border */
    [data-testid="assistant"] {
        display: flex;
        justify-content: flex-start;
    }
    
    [data-testid="assistant"] > div {
        background: linear-gradient(135deg, var(--card-bg) 0%, var(--card-bg) 100%) !important;
        color: var(--text-primary) !important;
        padding: 2rem !important;
        border-radius: 1.5rem !important;
        max-width: 90% !important;
        font-size: 0.975rem !important;
        line-height: 1.75 !important;
        border: 1px solid var(--card-border) !important;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25), 0 2px 8px rgba(0, 0, 0, 0.15) !important;
        position: relative !important;
        overflow: hidden !important;
        backdrop-filter: blur(12px) !important;
        transition: all 0.3s ease !important;
    }
    
    /* Light theme adjustments for assistant messages */
    .light-theme [data-testid="assistant"] > div {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.04) !important;
    }
    
    .light-theme [data-testid="assistant"] > div:hover {
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.1), 0 3px 6px rgba(0, 0, 0, 0.06) !important;
    }
    
    /* Subtle gradient overlay on assistant messages */
    [data-testid="assistant"] > div::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 2px;
        background: linear-gradient(90deg, transparent, rgba(120, 119, 198, 0.5), transparent);
        opacity: 0.6;
    }
    
    [data-testid="assistant"] > div:hover {
        border-color: rgba(255, 255, 255, 0.12) !important;
        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.3), 0 4px 12px rgba(0, 0, 0, 0.2) !important;
        transform: translateY(-2px) !important;
    }
    
    /* ==================== MESSAGE CONTENT STYLING - ENHANCED TYPOGRAPHY ==================== */
    .stMarkdown {
        color: #e8e8e8 !important;
    }
    
    .stMarkdown p {
        margin-bottom: 1.25rem !important;
        line-height: 1.8 !important;
        color: #e0e0e0 !important;
    }
    
    .stMarkdown ul, .stMarkdown ol {
        margin: 1.25rem 0 !important;
        padding-left: 1.75rem !important;
    }
    
    .stMarkdown li {
        margin-bottom: 0.85rem !important;
        line-height: 1.75 !important;
        color: #d8d8d8 !important;
    }
    
    .stMarkdown strong {
        font-weight: 600 !important;
        color: #ffffff !important;
        text-shadow: 0 0 20px rgba(255, 255, 255, 0.15) !important;
    }
    
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
        color: #ffffff !important;
        font-weight: 600 !important;
        margin-top: 2rem !important;
        margin-bottom: 1.25rem !important;
        letter-spacing: -0.02em !important;
    }
    
    .stMarkdown h2 {
        font-size: 1.4rem !important;
        background: linear-gradient(135deg, #ffffff 0%, #c8c8c8 100%) !important;
        -webkit-background-clip: text !important;
        -webkit-text-fill-color: transparent !important;
        background-clip: text !important;
    }
    
    .stMarkdown h3 {
        font-size: 1.15rem !important;
        color: #f0f0f0 !important;
    }
    
    .stMarkdown hr {
        margin: 2.5rem 0 !important;
        border: none !important;
        height: 1px !important;
        background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.15), transparent) !important;
    }
    
    .stMarkdown code {
        background: rgba(20, 20, 35, 0.8) !important;
        color: #b8b8d8 !important;
        padding: 0.25rem 0.6rem !important;
        border-radius: 0.5rem !important;
        font-size: 0.9rem !important;
        font-family: 'SF Mono', 'Monaco', 'Courier New', monospace !important;
        border: 1px solid rgba(120, 119, 198, 0.2) !important;
        font-weight: 500 !important;
    }
    
    /* Enhanced blockquote styling */
    .stMarkdown blockquote {
        border-left: 3px solid rgba(120, 119, 198, 0.5) !important;
        padding-left: 1.5rem !important;
        margin: 1.5rem 0 !important;
        color: #c0c0c0 !important;
        font-style: italic !important;
        background: rgba(120, 119, 198, 0.03) !important;
        padding: 1rem 1.5rem !important;
        border-radius: 0.5rem !important;
    }
    
    /* ==================== STATUS INDICATORS - REFINED ==================== */
    .stChatMessage [data-testid="stInfo"] {
        background: rgba(120, 119, 198, 0.08) !important;
        border: 1px solid rgba(120, 119, 198, 0.15) !important;
        border-radius: 0.75rem !important;
        color: #a8a8a8 !important;
        padding: 1rem 1.25rem !important;
        font-size: 0.925rem !important;
        font-weight: 400 !important;
        backdrop-filter: blur(8px) !important;
    }
    

    
    /* ==================== INPUT AREA - PREMIUM GLASS MORPHISM ==================== */
    .stChatInputContainer {
        background: linear-gradient(135deg, rgba(35, 35, 60, 0.85) 0%, rgba(25, 25, 45, 0.9) 100%) !important;
        border: 1px solid rgba(120, 119, 198, 0.25) !important;
        border-radius: 1.75rem !important;
        padding: 0.85rem 1.5rem !important;
        transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1) !important;
        backdrop-filter: blur(16px) !important;
        box-shadow: 
            0 8px 32px rgba(0, 0, 0, 0.3),
            0 2px 8px rgba(0, 0, 0, 0.2),
            inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
        position: relative !important;
    }
    
    /* Glow effect on focus */
    .stChatInputContainer::before {
        content: '';
        position: absolute;
        top: -2px;
        left: -2px;
        right: -2px;
        bottom: -2px;
        background: linear-gradient(135deg, rgba(120, 119, 198, 0.4), rgba(255, 107, 107, 0.2));
        border-radius: 1.85rem;
        opacity: 0;
        transition: opacity 0.4s ease;
        z-index: -1;
    }
    
    .stChatInputContainer:focus-within::before {
        opacity: 1;
    }
    
    .stChatInputContainer:focus-within {
        border-color: rgba(120, 119, 198, 0.45) !important;
        box-shadow: 
            0 12px 48px rgba(120, 119, 198, 0.15),
            0 4px 16px rgba(0, 0, 0, 0.25),
            inset 0 1px 0 rgba(255, 255, 255, 0.08) !important;
        transform: translateY(-2px) scale(1.005) !important;
    }
    
    .stChatInput textarea {
        background: transparent !important;
        color: #f0f0f0 !important;
        font-size: 0.975rem !important;
        line-height: 1.6 !important;
        border: none !important;
        caret-color: rgba(120, 119, 198, 0.8) !important;
        font-weight: 400 !important;
    }
    
    .stChatInput textarea::placeholder {
        color: #888888 !important;
        font-weight: 400 !important;
        opacity: 0.8 !important;
    }
    
    .stChatInput textarea:focus {
        outline: none !important;
        box-shadow: none !important;
    }
    
    /* Send button enhancement (if visible) */
    .stChatInputContainer button {
        background: linear-gradient(135deg, rgba(120, 119, 198, 0.2), rgba(120, 119, 198, 0.3)) !important;
        border: 1px solid rgba(120, 119, 198, 0.4) !important;
        border-radius: 0.75rem !important;
        color: #ffffff !important;
        transition: all 0.3s ease !important;
    }
    
    .stChatInputContainer button:hover {
        background: linear-gradient(135deg, rgba(120, 119, 198, 0.35), rgba(120, 119, 198, 0.45)) !important;
        border-color: rgba(120, 119, 198, 0.6) !important;
        transform: scale(1.05) !important;
    }
    
    /* ==================== SCROLLBAR - SLEEK & MODERN ==================== */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    
    ::-webkit-scrollbar-track {
        background: rgba(0, 0, 0, 0.2);
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(180deg, rgba(120, 119, 198, 0.4), rgba(120, 119, 198, 0.6));
        border-radius: 10px;
        border: 2px solid transparent;
        background-clip: padding-box;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(180deg, rgba(120, 119, 198, 0.6), rgba(120, 119, 198, 0.8));
    }
    
    /* ==================== LINKS - ELEGANT UNDERLINE ==================== */
    a {
        color: rgba(168, 168, 255, 0.95) !important;
        text-decoration: none !important;
        border-bottom: 1px solid rgba(168, 168, 255, 0.3) !important;
        transition: all 0.25s ease !important;
        padding-bottom: 1px !important;
    }
    
    a:hover {
        color: rgba(200, 200, 255, 1) !important;
        border-bottom-color: rgba(168, 168, 255, 0.8) !important;
        text-shadow: 0 0 8px rgba(168, 168, 255, 0.3) !important;
    }
    
    /* ==================== ANIMATIONS - SMOOTH & SOPHISTICATED ==================== */
    @keyframes fadeIn {
        from {
            opacity: 0;
            transform: translateY(12px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    @keyframes fadeInDown {
        from {
            opacity: 0;
            transform: translateY(-20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    @keyframes slideInRight {
        from {
            opacity: 0;
            transform: translateX(30px) scale(0.95);
        }
        to {
            opacity: 1;
            transform: translateX(0) scale(1);
        }
    }
    
    @keyframes slideInLeft {
        from {
            opacity: 0;
            transform: translateX(-30px) scale(0.95);
        }
        to {
            opacity: 1;
            transform: translateX(0) scale(1);
        }
    }
    
    @keyframes pulse {
        0%, 100% {
            opacity: 1;
        }
        50% {
            opacity: 0.4;
        }
    }
    
    @keyframes typing {
        0%, 100% {
            opacity: 0.25;
            transform: scale(0.9);
        }
        50% {
            opacity: 1;
            transform: scale(1.1);
        }
    }
    
    @keyframes shimmer {
        0% {
            background-position: -1000px 0;
        }
        100% {
            background-position: 1000px 0;
        }
    }
    
    /* Message animations with stagger effect */
    .stChatMessage {
        animation: fadeIn 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    [data-testid="user"] {
        animation: slideInRight 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    
    [data-testid="assistant"] {
        animation: slideInLeft 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    
    /* Typing indicator with elegant animation */
    .typing-indicator {
        animation: pulse 1.8s ease-in-out infinite;
    }
    
    .typing-dot {
        animation: typing 1.6s infinite ease-in-out;
        display: inline-block;
    }
    
    .typing-dot:nth-child(2) {
        animation-delay: 0.2s;
    }
    
    .typing-dot:nth-child(3) {
        animation-delay: 0.4s;
    }
    
    /* ==================== RESPONSIVE DESIGN - MOBILE OPTIMIZED ==================== */
    @media (max-width: 768px) {
        .block-container {
            padding-top: 1.5rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
        
        h1 {
            font-size: 1.75rem !important;
        }
        
        [data-testid="stCaptionContainer"] {
            font-size: 0.925rem !important;
        }
        
        [data-testid="user"] > div,
        [data-testid="assistant"] > div {
            max-width: 95% !important;
            padding: 1rem 1.25rem !important;
        }
        
        [data-testid="assistant"] > div {
            padding: 1.5rem !important;
        }
    }
    
    /* ==================== WELCOME CARD STYLING ==================== */
    .welcome-card {
        background: linear-gradient(135deg, rgba(26, 26, 46, 0.6) 0%, rgba(15, 15, 30, 0.8) 100%) !important;
        border: 1px solid rgba(120, 119, 198, 0.2) !important;
        border-radius: 1.5rem !important;
        padding: 2rem !important;
        margin: 2rem 0 !important;
        text-align: center !important;
        backdrop-filter: blur(12px) !important;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2) !important;
        animation: fadeIn 0.8s ease-out 0.4s both !important;
    }
    
    .welcome-card:hover {
        border-color: rgba(120, 119, 198, 0.35) !important;
        box-shadow: 0 12px 48px rgba(120, 119, 198, 0.15) !important;
        transform: translateY(-2px) !important;
        transition: all 0.4s ease !important;
    }
</style>
"""



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
            if sources_text.startswith("•"):
                sources_text = sources_text[1:].strip()
            
            # Split by bullet (•) or comma
            if " • " in sources_text:
                parts = [p.strip() for p in sources_text.split(" • ") if p.strip()]
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
                <label for="fb-{message_id}-up" class="feedback-btn thumbs-up" title="Helpful">👍</label>

                <input type="radio" name="fb-{message_id}" id="fb-{message_id}-down" class="fb-radio" />
                <label for="fb-{message_id}-down" class="feedback-btn thumbs-down" title="Not helpful">👎</label>
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
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


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

    st.markdown(MINIMAL_CSS, unsafe_allow_html=True)

    if not ensure_authenticated():
        return

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
                console.log(`✅ Feedback recorded: message ${messageId} = ${sentiment}`);
            });
            
            console.log('🎨 Feedback system ready');
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )

    # Get user information from Streamlit's built-in auth
    # Support developer fallback (local testing) via `st.session_state['dev_email']`
    if st.session_state.get("dev_email"):
        user_email = st.session_state.get("dev_email").lower()
        user_name = user_email.split("@")[0]
        user_role = _derive_role(user_email)
        st.sidebar.markdown("**Note:** Running in developer fallback auth mode")
    else:
        user_email = getattr(st.user, 'email', getattr(st.user, 'sub', 'unknown'))
        user_email = str(user_email).lower() if user_email else 'unknown'
        user_role = _derive_role(user_email)
        user_name = getattr(st.user, 'name', user_email.split('@')[0] if '@' in user_email else user_email)
    
    # Professional header with enhanced styling, user info, and logout
    st.markdown(f"""
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.5rem;">
        <div style="display: flex; align-items: center; gap: 1rem;">
            <div style="
                width: 56px; 
                height: 56px; 
                background: linear-gradient(135deg, #7877c6 0%, #9b8fd9 100%);
                border-radius: 14px;
                display: flex;
                align-items: center;
                justify-content: center;
                box-shadow: 0 4px 12px rgba(120, 119, 198, 0.3);
            ">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M20 6H12L10 4H4C2.9 4 2 4.9 2 6V18C2 19.1 2.9 20 4 20H20C21.1 20 22 19.1 22 18V8C22 6.9 21.1 6 20 6Z" fill="white" opacity="0.9"/>
                    <path d="M12 9C10.34 9 9 10.34 9 12C9 13.66 10.34 15 12 15C13.66 15 15 13.66 15 12C15 10.34 13.66 9 12 9Z" fill="white"/>
                </svg>
            </div>
            <div>
                <h1 style="margin: 0 !important; padding: 0 !important;">Inara</h1>
            </div>
        </div>
        <div style="text-align: right;">
            <div style="font-size: 0.875rem; color: rgba(255, 255, 255, 0.9); font-weight: 500;">
                {user_name}
            </div>
            <div style="font-size: 0.75rem; color: rgba(255, 255, 255, 0.6);">
                {user_role.title()} Access
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.caption("Your intelligent HR companion for policies, benefits, and workplace guidance — available 24/7")
    col_logout = st.container()
    with col_logout:
        if st.button('Sign out', key='logout_btn'):
            # Clear session state and use Streamlit's built-in logout when available
            for k in ['dev_email', 'logged_in_email', '_pkce_verifier', '_oauth_state']:
                if k in st.session_state:
                    del st.session_state[k]
                try:
                    st.logout()
                except Exception:
                    # If st.logout is not available locally, just clear query params and rerun
                    _clear_query_params()
            _rerun()
    
    # Enhanced welcome message for first-time users
    if len(st.session_state.get("history", [])) == 0:
        st.markdown("""
        <div class="welcome-card">
            <div style="font-size: 2.5rem; margin-bottom: 1rem;">👋</div>
            <div style="font-size: 1.2rem; color: #ffffff; font-weight: 600; margin-bottom: 1rem;">
                Welcome! How can I assist you today?
            </div>
            <div style="font-size: 0.975rem; color: #b8b8b8; line-height: 1.7; max-width: 600px; margin: 0 auto;">
                I'm here to help with company policies, leave requests, benefits, procedures, and more.<br/>
                <span style="margin-top: 1rem; display: inline-block;">
                    Try asking: <span style="color: #d8d8d8; font-weight: 500;">"What is the sick leave policy?"</span><br/>
                    or <span style="color: #d8d8d8; font-weight: 500;">"How do I request vacation time?"</span>
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)

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
    current_email = _get_current_email() or 'unknown'
    user_role = _derive_role(current_email)

    # Debug: Show loading status
    with st.spinner(f"🔐 Initializing {user_role.title()} HR Assistant..."):
        try:
            bot = load_bot(user_role=user_role)
            st.success(f"✅ {user_role.title()} HR Assistant loaded successfully!")
        except Exception as e:
            st.error(f"❌ Failed to load HR Assistant: {e}")
            st.error("Please try refreshing the page or contact support.")
            st.stop()

    executor = get_executor()
    
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
            if st.button("🔄 Refresh S3 Docs", key="s3_refresh_btn", help="Download the latest HR policy documents from S3. Use this when new policies are uploaded.", use_container_width=True):
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
                        print(f"🗑️  Deleted .rag_index directory")
                    
                    # CRITICAL FIX #2: Clear in-memory RAG tool cache
                    HrBot.clear_rag_cache()
                    
                    # CRITICAL FIX #3: Clear Streamlit resource cache (bot instance)
                    load_bot.clear()
                    print(f"🗑️  Cleared Streamlit resource cache")
                    
                    # Clear session state bot instance
                    if 'bot_instance' in st.session_state:
                        del st.session_state['bot_instance']
                    
                    st.session_state["s3_refresh_msg"] = f"✅ Refreshed {len(document_paths)} HR documents from S3 and rebuilt RAG indexes!"
                    _rerun()
                except Exception as e:
                    st.session_state["s3_refresh_msg"] = f"❌ Error refreshing S3 documents: {e}"
                    _rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        
        # Clear Cache Button (Red - Right)
        with col2:
            st.markdown('<div class="clear-cache-container">', unsafe_allow_html=True)
            if st.button("🗑️ Clear Response Cache", key="clear_cache_btn", help="Clear cached responses. Use this if you get a technical error and want to retry your query.", use_container_width=True):
                try:
                    bot.response_cache.clear_all()
                    st.session_state["cache_cleared_msg"] = "✅ Response cache cleared successfully! You can now retry your query."
                    _rerun()
                except Exception as e:
                    st.session_state["cache_cleared_msg"] = f"❌ Error clearing cache: {e}"
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
                st.session_state.history.append({"role": "assistant", "content": formatted})
                del st.session_state.pending_response
                _rerun()
            except Exception as e:
                # Show error with cache clear suggestion
                st.error(f"⚠️ Technical Error: {e}")
                st.warning("💡 **Tip:** This error response has been cached. To retry your query successfully, please click the '🗑️ Clear Cache' button in the top right corner, then ask your question again.")
                del st.session_state.pending_response
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

    # Chat input - DON'T render immediately, just add to history
    if prompt := st.chat_input(DEFAULT_PLACEHOLDER):
        history_context = build_history_context(st.session_state["history"], prompt)
        augmented_question = build_augmented_question(st.session_state["history"], prompt)
        # Add to history (will be rendered on next rerun)
        st.session_state["history"].append({"role": "user", "content": prompt})
        # Start processing
        future = executor.submit(query_bot, bot, prompt, history_context, augmented_question)
        st.session_state["pending_response"] = {"future": future, "start_time": time.time()}
        _rerun()


if __name__ == "__main__":
    main()
