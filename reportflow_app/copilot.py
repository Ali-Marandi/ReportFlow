"""Governed AI Copilot provider adapters for ReportFlow v2.0.

Only semantic metadata and deterministic metric results are sent to an LLM.
Credentials are resolved at runtime from the operating-system vault and are never
stored in semantic definitions, report records, prompts, or audit details.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Protocol

from reportflow_app.core import CredentialVault, ProjectStore, ReportFlowError
from reportflow_app.enterprise import CopilotAnswer, CopilotGroundingService, CopilotRequest


class CopilotProvider(Protocol):
    def generate(self, request: CopilotRequest) -> CopilotAnswer: ...


class OpenAICompatibleCopilot:
    """OpenAI-compatible, structured-output adapter with policy-safe grounding.

    The caller must configure a model endpoint and a *credential reference*. The
    actual API key is retrieved from ``CredentialVault`` only at call time.
    """

    RESPONSE_SCHEMA = {
        "type": "json_schema",
        "json_schema": {
            "name": "reportflow_copilot_answer",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                    "cited_metric_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "needs_review": {"type": "boolean"},
                },
                "required": ["answer", "assumptions", "cited_metric_ids", "confidence", "needs_review"],
                "additionalProperties": False,
            },
        },
    }

    def __init__(self, store: ProjectStore, base_url: str, credential_reference: str, model: str = "gpt-5-mini") -> None:
        if not base_url.startswith("https://"):
            raise ReportFlowError("AI Copilot endpoints must use HTTPS.")
        self.store = store
        self.base_url = base_url.rstrip("/")
        self.credential_reference = credential_reference
        self.model = model
        self.grounding_service = CopilotGroundingService()

    def generate(self, request: CopilotRequest) -> CopilotAnswer:
        secret = CredentialVault.get_secret(self.credential_reference)
        if not secret:
            raise ReportFlowError("The AI provider credential cannot be found in the operating-system vault.")
        try:
            from openai import OpenAI  # type: ignore[import-not-found]
        except ImportError as error:
            raise ReportFlowError("AI Copilot requires the optional 'openai' enterprise dependency.") from error
        messages = [
            {
                "role": "system",
                "content": (
                    "You are ReportFlow Copilot. Answer only from the governed semantic grounding provided. "
                    "Never invent a metric, number, data source, filter, or business definition. "
                    "Always cite one or more metric IDs. If the grounding is incomplete, set needs_review=true."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"question": request.question, "grounding": request.grounding}, ensure_ascii=False),
            },
        ]
        client = OpenAI(base_url=self.base_url, api_key=secret)
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format=self.RESPONSE_SCHEMA,
                max_completion_tokens=1200,
            )
            content = response.choices[0].message.content
            if not content:
                raise ReportFlowError("The AI provider returned an empty response.")
            answer = self.grounding_service.validate_answer(request, json.loads(content))
        except ReportFlowError:
            raise
        except Exception as error:
            raise ReportFlowError(f"AI Copilot request failed: {error}") from error
        self.store.audit(
            "copilot.generated",
            "semantic_model",
            request.semantic_model_id,
            {
                "actor": request.actor,
                "model": self.model,
                "semantic_version": request.semantic_model_version,
                "cited_metric_ids": answer.cited_metric_ids,
                "confidence": answer.confidence,
                "needs_review": answer.needs_review,
            },
        )
        return answer
