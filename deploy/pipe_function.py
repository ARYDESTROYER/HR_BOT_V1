"""
title: Inara HR Assistant Pipe
author: Inara Team
version: 1.0.0
required_open_webui_version: 0.4.0
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import requests
from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        BACKEND_BASE_URL: str = Field(
            default="http://127.0.0.1:8502",
            description="Base URL of the Inara FastAPI backend bridge",
        )
        BACKEND_MODEL_ID: str = Field(
            default="inara-hr-assistant",
            description="Model ID exposed by the backend /v1/models endpoint",
        )
        REQUEST_TIMEOUT_SECONDS: int = Field(
            default=300,
            description="HTTP timeout (seconds) when calling backend",
        )
        NAME_PREFIX: str = Field(
            default="INARA/",
            description="Prefix shown in Open WebUI model selector",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    def _stream_text_chunks(self, response: requests.Response):
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue

            line = raw_line.strip()
            if not line.startswith("data:"):
                continue

            payload = line[5:].strip()
            if payload == "[DONE]":
                break

            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue

            choices = chunk.get("choices") or []
            if not choices:
                continue

            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                yield content

    def pipes(self) -> List[Dict[str, str]]:
        return [
            {
                "id": self.valves.BACKEND_MODEL_ID,
                "name": f"{self.valves.NAME_PREFIX}HR Assistant",
            }
        ]

    async def pipe(self, body: dict, __user__: dict) -> Any:
        user_email = ((__user__ or {}).get("email") or "").strip().lower()
        if not user_email:
            return {
                "error": {
                    "message": "Missing user identity in Open WebUI session.",
                    "type": "authentication_error",
                }
            }

        selected_model = body.get("model") or self.valves.BACKEND_MODEL_ID
        if "." in selected_model:
            selected_model = selected_model.split(".", 1)[1]

        payload = {
            **body,
            "model": selected_model,
            "user": user_email,
            "stream": bool(body.get("stream", False)),
        }

        endpoint = f"{self.valves.BACKEND_BASE_URL.rstrip('/')}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                stream=payload["stream"],
                timeout=self.valves.REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return {
                "error": {
                    "message": f"Backend request failed: {exc}",
                    "type": "connection_error",
                }
            }

        if payload["stream"]:
            return self._stream_text_chunks(response)

        try:
            return response.json()
        except ValueError:
            return {
                "error": {
                    "message": "Backend returned invalid JSON response.",
                    "type": "backend_error",
                }
            }
