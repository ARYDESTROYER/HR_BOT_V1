"""FastAPI bridge exposing OpenAI-compatible endpoints for Open WebUI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from hr_bot.crew import HrBot
from hr_bot.utils.s3_loader import S3DocumentLoader

load_dotenv()

logger = logging.getLogger("hr_bot.api")

APP_NAME = os.getenv("APP_NAME", "Inara")
API_MODEL_ID = os.getenv("HR_BOT_MODEL_ID", "inara-hr-assistant")
BOT_USE_S3 = os.getenv("HR_BOT_USE_S3", "true").strip().lower() in {"1", "true", "yes"}

BOT_CACHE: Dict[str, HrBot] = {}
BOT_LOCKS: Dict[str, asyncio.Lock] = {}


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Any


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    user: Optional[str] = None


class AdminActionRequest(BaseModel):
    email: str = Field(..., description="Admin user email for allow-list check")
    role: str = Field(default="employee", description="Target role for operation")


app = FastAPI(title="Inara API Bridge", version="1.0.0")


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


def _is_admin(email: Optional[str]) -> bool:
    normalized = _normalize_email(email)
    if not normalized:
        return False
    return normalized in _env_list("ADMIN_EMAILS")


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _get_lock(role: str) -> asyncio.Lock:
    lock = BOT_LOCKS.get(role)
    if lock is None:
        lock = asyncio.Lock()
        BOT_LOCKS[role] = lock
    return lock


async def _get_bot(role: str) -> HrBot:
    role_key = (role or "employee").lower()
    if role_key in BOT_CACHE:
        return BOT_CACHE[role_key]

    lock = _get_lock(role_key)
    async with lock:
        if role_key in BOT_CACHE:
            return BOT_CACHE[role_key]
        bot = await run_in_threadpool(HrBot, role_key, BOT_USE_S3)
        BOT_CACHE[role_key] = bot
        return bot


def _coerce_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part).strip()
    if content is None:
        return ""
    return str(content).strip()


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
            if "•" in sources_text:
                bullet_sep = " • "
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
    return text.replace("```markdown", "").replace("```", "").strip()


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
    formatted = clean_markdown_artifacts(answer)
    formatted = remove_document_evidence_section(formatted)
    return format_sources(formatted)


def _extract_prompt_and_history(messages: List[ChatMessage]) -> tuple[str, List[Dict[str, str]]]:
    history: List[Dict[str, str]] = []
    for msg in messages:
        text = _coerce_text_content(msg.content)
        if text:
            history.append({"role": msg.role, "content": text})

    user_messages = [msg for msg in history if msg["role"] == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="At least one user message is required")

    prompt = user_messages[-1]["content"].strip()
    prior_history = history[:-1]
    return prompt, prior_history


def _log_query(
    email: str,
    query: str,
    cached: bool = False,
    duration: float = 0.0,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost: float | None = None,
) -> None:
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "queries.jsonl"

    total_tokens = None
    if tokens_in is not None or tokens_out is not None:
        total_tokens = (tokens_in or 0) + (tokens_out or 0)

    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": email,
        "query": query[:200],
        "cached": cached,
        "duration": f"{duration:.2f}s" if duration else None,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": total_tokens,
        "cost": round(cost, 6) if cost is not None else None,
    }

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning("Failed to log query: %s", exc)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models() -> Dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": API_MODEL_ID,
                "object": "model",
                "created": int(time.time()),
                "owned_by": APP_NAME,
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(payload: ChatCompletionRequest, request: Request) -> Any:

    email = _normalize_email(payload.user)
    role = _derive_role(email)
    if role == "unauthorized":
        raise HTTPException(status_code=403, detail="Unauthorized user")

    prompt, history = _extract_prompt_and_history(payload.messages)
    history_context = build_history_context(history, prompt)
    augmented_question = build_augmented_question(history, prompt)

    bot = await _get_bot(role)

    start_time = time.time()

    def _call_bot() -> str:
        return bot.query_with_cache(
            query=prompt,
            context=history_context or "",
            retrieval_query=augmented_question,
        )

    try:
        answer = await run_in_threadpool(_call_bot)
    except Exception as exc:
        logger.exception("Failed to process chat completion", exc_info=exc)
        raise HTTPException(status_code=500, detail="Failed to generate response") from exc

    duration = time.time() - start_time
    cached = duration < 1.0

    usage = getattr(bot, "last_usage", None) or {}
    tokens_in = usage.get("tokens_in")
    tokens_out = usage.get("tokens_out")
    cost = usage.get("cost")

    if tokens_in is None:
        tokens_in = _estimate_tokens(prompt)
    if tokens_out is None:
        tokens_out = _estimate_tokens(answer)

    _log_query(
        email=email,
        query=prompt,
        cached=cached,
        duration=duration,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=cost,
    )

    content = format_answer(answer)
    completion_id = f"chatcmpl-{int(time.time() * 1000)}"
    created = int(time.time())

    response_payload = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": payload.model or API_MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": tokens_in,
            "completion_tokens": tokens_out,
            "total_tokens": (tokens_in or 0) + (tokens_out or 0),
        },
    }

    if payload.stream:
        async def _stream_once():
            stream_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": payload.model or API_MODEL_ID,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(stream_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_stream_once(), media_type="text/event-stream")

    return response_payload


async def _require_admin_or_403(body: AdminActionRequest) -> None:
    if not _is_admin(body.email):
        raise HTTPException(status_code=403, detail="Admin access required")


@app.post("/admin/cache-clear")
async def admin_clear_cache(body: AdminActionRequest) -> Dict[str, str]:
    await _require_admin_or_403(body)
    role = (body.role or "employee").lower()
    bot = BOT_CACHE.get(role)
    if bot is None:
        bot = await _get_bot(role)
    await run_in_threadpool(bot.response_cache.clear_all)
    return {"status": "ok", "message": f"Response cache cleared for role={role}"}


@app.post("/admin/s3-refresh")
async def admin_refresh_s3(body: AdminActionRequest) -> Dict[str, str]:
    await _require_admin_or_403(body)
    role = (body.role or "employee").lower()

    def _refresh() -> int:
        loader = S3DocumentLoader(user_role=role)
        loader.clear_cache()
        document_paths = loader.load_documents(force_refresh=True)
        rag_index_dir = Path(".rag_index")
        if rag_index_dir.exists():
            shutil.rmtree(rag_index_dir)
        HrBot.clear_rag_cache()
        BOT_CACHE.pop(role, None)
        return len(document_paths)

    count = await run_in_threadpool(_refresh)
    return {"status": "ok", "message": f"Refreshed {count} S3 documents for role={role}"}


@app.post("/admin/rag-rebuild")
async def admin_rag_rebuild(body: AdminActionRequest) -> Dict[str, str]:
    await _require_admin_or_403(body)
    role = (body.role or "employee").lower()

    def _rebuild() -> None:
        HrBot.clear_rag_cache()
        BOT_CACHE.pop(role, None)

    await run_in_threadpool(_rebuild)
    await _get_bot(role)
    return {"status": "ok", "message": f"RAG cache rebuilt for role={role}"}
