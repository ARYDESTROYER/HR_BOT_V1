"""Chainlit front-end for the Inara HR Assistant."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Dict, List, Optional

import chainlit as cl
from starlette.datastructures import Headers

from hr_bot.crew import HrBot
from hr_bot.utils.s3_loader import S3DocumentLoader

logger = logging.getLogger("hr_bot.chainlit")

# ---------------------------------------------------------------------------
# Environment wiring
# ---------------------------------------------------------------------------

_ENV_ALIAS_MAP = {
    "OAUTH_GOOGLE_CLIENT_ID": "GOOGLE_CLIENT_ID",
    "OAUTH_GOOGLE_CLIENT_SECRET": "GOOGLE_CLIENT_SECRET",
}
for target, source in _ENV_ALIAS_MAP.items():
    if not os.getenv(target) and os.getenv(source):
        os.environ[target] = os.environ[source]

if not os.getenv("CHAINLIT_AUTH_SECRET"):
    os.environ["CHAINLIT_AUTH_SECRET"] = os.getenv("CHAINLIT_JWT_SECRET", "inara-demo-secret")
    logger.warning(
        "CHAINLIT_AUTH_SECRET missing. A temporary value was injected for development. "
        "Run `chainlit create-secret` and set CHAINLIT_AUTH_SECRET before production deploys."
    )

SUPPORT_CONTACT_EMAIL = os.getenv("SUPPORT_CONTACT_EMAIL", "support@company.com")
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
]

EXECUTOR = ThreadPoolExecutor(max_workers=int(os.getenv("CHAINLIT_MAX_WORKERS", "4")))
BOT_CACHE: Dict[str, HrBot] = {}
BOT_LOCKS: Dict[str, asyncio.Lock] = {}
WARMED_ROLES: set[str] = set()


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _env_flag(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes"}


def _env_list(key: str) -> List[str]:
    values = os.getenv(key, "")
    return [item.strip().lower() for item in values.split(",") if item.strip()]


def _normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def _derive_role(email: Optional[str]) -> str:
    normalized = _normalize_email(email)
    if not normalized:
        return "unauthorized"
    if normalized in _env_list("EXECUTIVE_EMAILS"):
        return "executive"
    if normalized in _env_list("EMPLOYEE_EMAILS"):
        return "employee"
    return "unauthorized"


def _display_name(email: str, fallback: Optional[str]) -> str:
    if fallback:
        return fallback
    if "@" in email:
        return email.split("@", 1)[0]
    return email or "Colleague"


def _history() -> List[Dict[str, str]]:
    return cl.user_session.get("history", [])


def _set_history(history: List[Dict[str, str]]) -> None:
    cl.user_session.set("history", history)


def _get_lock(role: str) -> asyncio.Lock:
    lock = BOT_LOCKS.get(role)
    if lock is None:
        lock = asyncio.Lock()
        BOT_LOCKS[role] = lock
    return lock


async def _run_blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(EXECUTOR, partial(func, *args, **kwargs))


async def _get_bot(role: str) -> HrBot:
    role_key = (role or "employee").lower()
    if cached := BOT_CACHE.get(role_key):
        return cached
    lock = _get_lock(role_key)
    async with lock:
        if cached := BOT_CACHE.get(role_key):
            return cached
        logger.info("Initializing HrBot for role=%s", role_key)
        bot = await _run_blocking(HrBot, role_key, True)
        BOT_CACHE[role_key] = bot
        return bot


def _warm_bot(bot: HrBot) -> None:
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
    except Exception as exc:
        logger.warning("Warm-up skipped: %s", exc)


async def _ensure_warm(role: str, bot: HrBot) -> None:
    role_key = (role or "employee").lower()
    if role_key in WARMED_ROLES:
        return
    await _run_blocking(_warm_bot, bot)
    WARMED_ROLES.add(role_key)


def format_sources(answer: str) -> str:
    lines = answer.splitlines()
    if not lines:
        return answer
    for idx, line in enumerate(lines):
        if line.lower().startswith("sources:"):
            sources_text = line.split(":", 1)[1].strip()
            if sources_text.startswith("-"):
                sources_text = sources_text[1:].strip()
            bullet_sep = " - "
            if "\u2022" in sources_text:
                bullet_sep = " \u2022 "
            if bullet_sep.strip() and bullet_sep in sources_text:
                parts = [p.strip() for p in sources_text.split(bullet_sep) if p.strip()]
            else:
                parts = [p.strip() for p in sources_text.split(",") if p.strip()]
            formatted = []
            for part in parts:
                file_name = part.strip()
                if not file_name:
                    continue
                import re

                file_name = re.sub(r"^\[\d+\]\s*", "", file_name)
                file_name = re.sub(r"^\d+\.\s*", "", file_name)
                display_name = file_name.replace("_", " ")
                formatted.append(f"`{display_name}`")
            if formatted:
                lines[idx] = f"\n\n---\n\n**Sources:** {' · '.join(formatted)}"
            else:
                lines[idx] = ""
            break
    return "\n".join(lines)


def clean_markdown_artifacts(text: str) -> str:
    text = text.replace("```markdown", "").replace("```", "")
    return text.strip()


def remove_document_evidence_section(text: str) -> str:
    lines = text.splitlines()
    output: List[str] = []
    in_block = False
    for line in lines:
        if "document evidence" in line.lower() and ("##" in line or "**" in line):
            in_block = True
            continue
        if in_block:
            if (
                line.lower().startswith("sources:")
                or "**sources:**" in line.lower()
                or (line.startswith("##") and "document evidence" not in line.lower())
            ):
                in_block = False
                output.append(line)
            continue
        output.append(line)
    return "\n".join(output)


def format_answer(answer: str) -> str:
    if not answer:
        return "I'm sorry, I couldn't generate a response."
    answer = clean_markdown_artifacts(answer)
    answer = remove_document_evidence_section(answer)
    answer = format_sources(answer)
    return answer


def build_history_context(history: List[Dict[str, str]], question: Optional[str] = None, max_turns: int = 3) -> str:
    if not history and not question:
        return ""
    max_messages = max_turns * 2
    recent = history[-max_messages:] if len(history) > max_messages else history
    context_parts: List[str] = []
    if recent:
        context_parts.append("Recent conversation:")
        for msg in recent:
            role = msg.get("role", "")
            content = (msg.get("content") or "")[:300]
            if role == "user":
                context_parts.append(f"User: {content}")
            elif role == "assistant":
                clean_content = content.split("Sources:")[0].strip()
                if clean_content:
                    context_parts.append(f"Assistant: {clean_content}")
    if question:
        context_parts.append(f"Current question: {question[:200]}")
    return "\n".join(context_parts)


def build_augmented_question(history: List[Dict[str, str]], question: str, max_turns: int = 2) -> str:
    if not history:
        return question.strip()
    max_messages = max_turns * 2
    recent = history[-max_messages:] if len(history) > max_messages else history
    lines: List[str] = []
    for msg in recent:
        role = msg.get("role", "").lower()
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if role == "assistant":
            clean_content = content.split("Sources:")[0].strip()
            if clean_content:
                lines.append(f"Assistant previously said: {clean_content[:400]}")
        elif role == "user":
            lines.append(f"User previously asked: {content[:200]}")
    if not lines:
        return question.strip()
    lines.append(f"Follow-up question: {question.strip()}")
    return "\n".join(lines)


def _compose_dashboard(display_name: str, role: str) -> str:
    return (
        f"### Welcome back, {display_name}\n"
        f"Access level: **{role.title()}**\n\n"
        "Your intelligent HR companion for policies, benefits, and workplace guidance — available 24/7.\n\n"
        f"Need help signing in or resetting access? Email [{SUPPORT_CONTACT_EMAIL}](mailto:{SUPPORT_CONTACT_EMAIL})."
    )


async def _send_dashboard(display_name: str, role: str) -> None:
    actions = [
        cl.Action(
            name="refresh_s3_docs",
            payload={"role": role},
            label="Refresh S3 Docs",
            tooltip="Download the latest HR policies and rebuild indexes",
            icon="RefreshCw",
        ),
        cl.Action(
            name="clear_response_cache",
            payload={},
            label="Clear Response Cache",
            tooltip="Purge semantic cache for troubleshooting",
            icon="Eraser",
        ),
    ]
    message = cl.Message(
        author="Inara Control Center",
        content=_compose_dashboard(display_name, role),
        actions=actions,
    )
    await message.send()


async def _refresh_s3_documents(role: str) -> str:
    def _refresh() -> str:
        loader = S3DocumentLoader(user_role=role)
        loader.clear_cache()
        document_paths = loader.load_documents(force_refresh=True)
        rag_index_dir = Path(".rag_index")
        if rag_index_dir.exists():
            shutil.rmtree(rag_index_dir)
        HrBot.clear_rag_cache()
        BOT_CACHE.pop(role, None)
        return f"Refreshed {len(document_paths)} HR documents from S3 and rebuilt RAG indexes."

    return await _run_blocking(_refresh)


async def _clear_response_cache(role: str) -> str:
    bot = BOT_CACHE.get(role) or cl.user_session.get("bot")
    if not bot:
        bot = await _get_bot(role)
    await _run_blocking(bot.response_cache.clear_all)
    return "Response cache cleared successfully."


async def _query_bot(prompt: str) -> str:
    bot: HrBot = cl.user_session.get("bot")
    if bot is None:
        role = cl.user_session.get("role", "employee")
        bot = await _get_bot(role)
        cl.user_session.set("bot", bot)
    history = _history()
    history_context = build_history_context(history, prompt)
    augmented_question = build_augmented_question(history, prompt)

    def _call_bot() -> str:
        return bot.query_with_cache(
            query=prompt,
            context=history_context or "",
            retrieval_query=augmented_question,
        )

    return await _run_blocking(_call_bot)


# ---------------------------------------------------------------------------
# Authentication callbacks
# ---------------------------------------------------------------------------


@cl.oauth_callback
async def oauth_callback(
    provider_id: str,
    token: str,
    raw_user_data: Dict[str, str],
    default_user: cl.User,
    id_token: Optional[str] = None,
) -> Optional[cl.User]:
    email = _normalize_email(raw_user_data.get("email") or default_user.identifier)
    role = _derive_role(email)
    if role == "unauthorized":
        logger.warning("OAuth login rejected for %s", email)
        return None
    display_name = raw_user_data.get("name") or raw_user_data.get("given_name")
    default_user.identifier = email
    default_user.display_name = _display_name(email, display_name)
    metadata = default_user.metadata or {}
    metadata.update({"role": role, "email": email, "provider": provider_id})
    default_user.metadata = metadata
    return default_user


@cl.header_auth_callback
async def header_auth(headers: Headers) -> Optional[cl.User]:
    if not _env_flag("ALLOW_DEV_LOGIN"):
        return None
    email = _normalize_email(
        headers.get("x-forwarded-email")
        or headers.get("x-dev-email")
        or headers.get("x-user-email")
    )
    if not email:
        return None
    role = _derive_role(email)
    if role == "unauthorized":
        return None
    return cl.User(identifier=email, metadata={"role": role, "provider": "header"})


# ---------------------------------------------------------------------------
# Chainlit lifecycle
# ---------------------------------------------------------------------------


@cl.on_app_shutdown
async def shutdown() -> None:
    EXECUTOR.shutdown(wait=False, cancel_futures=True)


@cl.on_chat_start
async def on_chat_start() -> None:
    session_user = cl.user_session.get("user")
    email = _normalize_email(getattr(session_user, "identifier", None))
    role = "unauthorized"
    if session_user:
        role = session_user.metadata.get("role") or _derive_role(email)
    if role == "unauthorized":
        await cl.ErrorMessage(
            content=(
                "Access denied. This Chainlit workspace is limited to approved corporate emails. "
                f"Need assistance? Reach out to {SUPPORT_CONTACT_EMAIL}."
            )
        ).send()
        return
    display_name = _display_name(email, getattr(session_user, "display_name", None))
    cl.user_session.set("email", email)
    cl.user_session.set("role", role)
    cl.user_session.set("display_name", display_name)
    cl.user_session.set("history", [])

    bot = await _get_bot(role)
    cl.user_session.set("bot", bot)
    await _ensure_warm(role, bot)
    await _send_dashboard(display_name, role)
    await cl.Message(
        author="Inara",
        content=(
            "I'm online. Ask any HR policy, benefits, or workflow question using the chat input below.\n\n"
            f"_Tip_: {DEFAULT_PLACEHOLDER}"
        ),
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    prompt = (message.content or "").strip()
    if not prompt:
        return
    history = _history()
    history.append({"role": "user", "content": prompt})
    _set_history(history)

    progress = cl.Message(
        author="Inara",
        content="Analyzing your request...",
    )
    await progress.send()

    try:
        answer = await _query_bot(prompt)
    except Exception as exc:
        logger.exception("Failed to answer question", exc_info=exc)
        progress.content = (
            "⚠️ Technical issue while generating a response. Please try again or trigger "
            "'Clear Response Cache'."
        )
        await progress.update()
        return

    formatted = format_answer(answer)
    history.append({"role": "assistant", "content": formatted})
    _set_history(history)
    progress.content = formatted
    await progress.update()


@cl.action_callback("refresh_s3_docs")
async def refresh_docs(action: cl.Action) -> None:
    role = cl.user_session.get("role", "employee")
    await cl.Message(content="Refreshing S3 documents. This may take a minute...").send()
    try:
        status = await _refresh_s3_documents(role)
        await cl.Message(content=f"✅ {status}").send()
    except Exception as exc:
        logger.exception("S3 refresh failed", exc_info=exc)
        await cl.Message(content=f"⚠️ Error refreshing documents: {exc}").send()


@cl.action_callback("clear_response_cache")
async def clear_cache(action: cl.Action) -> None:
    role = cl.user_session.get("role", "employee")
    try:
        status = await _clear_response_cache(role)
        await cl.Message(content=f"🧹 {status}").send()
    except Exception as exc:
        logger.exception("Cache clear failed", exc_info=exc)
        await cl.Message(content=f"⚠️ Error clearing cache: {exc}").send()


@cl.on_stop
async def on_stop() -> None:
    cl.user_session.set("history", [])
    cl.user_session.set("bot", None)
