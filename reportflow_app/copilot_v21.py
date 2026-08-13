"""Governed narrative Copilot for ReportFlow v2.1.

LLM calls receive only already-calculated semantic evidence cards. The provider has
no connector, database, secret-manager, or raw-data access.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from reportflow_app.core import ProjectStore, ReportFlowError
from reportflow_app.semantic_v21 import EvidenceCard, SemanticContract
from reportflow_app.secrets import SecretProvider


CopilotIntent = Literal["summary", "variance_explanation", "outlier_review", "metric_glossary"]


@dataclass(frozen=True, slots=True)
class CopilotEvidencePolicy:
    allowed_sensitivities: frozenset[str] = frozenset({"public", "internal"})
    require_certified_metrics: bool = True
    require_fresh_data: bool = True
    max_question_characters: int = 4_000


@dataclass(frozen=True, slots=True)
class GovernedCopilotRequest:
    actor: str
    intent: CopilotIntent
    question: str
    semantic_model_id: str
    semantic_version: str
    evidence_cards: list[EvidenceCard]
    policy: CopilotEvidencePolicy
    prompt_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CopilotRecommendation:
    action: str
    rationale_metric_ids: list[str]


@dataclass(frozen=True, slots=True)
class GovernedCopilotAnswer:
    summary: str
    evidence: list[dict[str, Any]]
    drivers: list[str]
    assumptions: list[str]
    recommended_actions: list[CopilotRecommendation]
    confidence: Literal["low", "medium", "high"]
    needs_review: bool


class NarrativeCopilotProvider(Protocol):
    def generate(self, request: GovernedCopilotRequest) -> dict[str, Any]: ...


class CopilotNarrativeService:
    """Enforces semantic/policy gates before and after a narrative provider call."""

    ALLOWED_INTENTS = frozenset({"summary", "variance_explanation", "outlier_review", "metric_glossary"})

    def __init__(self, store: ProjectStore) -> None:
        self.store = store

    def prepare(
        self,
        actor: str,
        intent: CopilotIntent,
        question: str,
        contract: SemanticContract,
        cards: list[EvidenceCard],
        policy: CopilotEvidencePolicy = CopilotEvidencePolicy(),
    ) -> GovernedCopilotRequest:
        contract.validate()
        if contract.status != "published":
            raise ReportFlowError("Copilot can use only a published semantic contract.")
        if intent not in self.ALLOWED_INTENTS:
            raise ReportFlowError("Requested Copilot intent is not approved by policy.")
        question = question.strip()
        if not question or len(question) > policy.max_question_characters:
            raise ReportFlowError("Copilot question is empty or exceeds the policy character limit.")
        if not cards:
            raise ReportFlowError("Copilot requires deterministic semantic evidence before generation.")
        for card in cards:
            if card.sensitivity not in policy.allowed_sensitivities:
                raise ReportFlowError("Copilot evidence sensitivity is not approved for this deployment.")
            if policy.require_certified_metrics and not card.certified:
                raise ReportFlowError("Copilot evidence must come from certified metrics.")
        freshness = {card.freshness_status for card in cards}
        needs_review = "stale" in freshness or (policy.require_fresh_data and "unknown" in freshness)
        payload = {
            "intent": intent,
            "question": question,
            "semantic_contract": {
                "model_id": contract.model.id,
                "version": contract.model.version,
                "grain": contract.grain,
                "status": contract.status,
            },
            "evidence_cards": [asdict(card) for card in cards],
            "constraints": {
                "use_only_supplied_evidence": True,
                "must_cite_metric_ids": [card.metric_id for card in cards],
                "must_set_needs_review": needs_review,
                "do_not_request_or_emit_raw_rows": True,
            },
        }
        return GovernedCopilotRequest(actor, intent, question, contract.model.id, contract.model.version, cards, policy, payload)

    def invoke(self, provider: NarrativeCopilotProvider, request: GovernedCopilotRequest) -> GovernedCopilotAnswer:
        answer = self.validate_answer(request, provider.generate(request))
        self.store.audit(
            "copilot.v21.generated", "semantic_model", request.semantic_model_id,
            {
                "actor": request.actor,
                "intent": request.intent,
                "semantic_version": request.semantic_version,
                "metric_ids": [card.metric_id for card in request.evidence_cards],
                "confidence": answer.confidence,
                "needs_review": answer.needs_review,
            },
        )
        return answer

    def validate_answer(self, request: GovernedCopilotRequest, payload: dict[str, Any]) -> GovernedCopilotAnswer:
        required = {"summary", "evidence", "drivers", "assumptions", "recommended_actions", "confidence", "needs_review"}
        if set(payload) != required:
            raise ReportFlowError("Copilot v2.1 response does not match the governed response schema.")
        if payload["confidence"] not in {"low", "medium", "high"} or not isinstance(payload["needs_review"], bool):
            raise ReportFlowError("Copilot response has invalid confidence or review metadata.")
        allowed_ids = {card.metric_id for card in request.evidence_cards}
        evidence = payload["evidence"]
        if not isinstance(evidence, list) or not evidence:
            raise ReportFlowError("Copilot response must contain one or more evidence citations.")
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {"metric_id", "statement"} or item["metric_id"] not in allowed_ids:
                raise ReportFlowError("Copilot response cites a metric outside the governed evidence set.")
        recommendations: list[CopilotRecommendation] = []
        if not isinstance(payload["recommended_actions"], list):
            raise ReportFlowError("Copilot recommendations must be a structured list.")
        for item in payload["recommended_actions"]:
            if not isinstance(item, dict) or set(item) != {"action", "rationale_metric_ids"}:
                raise ReportFlowError("Copilot recommendation has an invalid shape.")
            metric_ids = item["rationale_metric_ids"]
            if not isinstance(metric_ids, list) or not metric_ids or any(value not in allowed_ids for value in metric_ids):
                raise ReportFlowError("Copilot recommendation lacks governed metric rationale.")
            recommendations.append(CopilotRecommendation(str(item["action"]), list(metric_ids)))
        for key in ("summary",):
            if not isinstance(payload[key], str) or not payload[key].strip():
                raise ReportFlowError("Copilot response summary must be nonempty text.")
        for key in ("drivers", "assumptions"):
            if not isinstance(payload[key], list) or any(not isinstance(value, str) for value in payload[key]):
                raise ReportFlowError("Copilot response has invalid narrative list fields.")
        expected_review = any(card.freshness_status != "fresh" for card in request.evidence_cards)
        if expected_review and not payload["needs_review"]:
            raise ReportFlowError("Copilot response must request review for stale or unknown evidence freshness.")
        return GovernedCopilotAnswer(
            summary=payload["summary"], evidence=list(evidence), drivers=list(payload["drivers"]), assumptions=list(payload["assumptions"]),
            recommended_actions=recommendations, confidence=payload["confidence"], needs_review=payload["needs_review"],
        )


class OpenAICompatibleNarrativeProvider:
    """Optional OpenAI-compatible provider using a secret reference and strict JSON schema."""

    RESPONSE_SCHEMA = {
        "type": "json_schema",
        "json_schema": {
            "name": "reportflow_v21_copilot_answer",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "object", "properties": {"metric_id": {"type": "string"}, "statement": {"type": "string"}}, "required": ["metric_id", "statement"], "additionalProperties": False}},
                    "drivers": {"type": "array", "items": {"type": "string"}},
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                    "recommended_actions": {"type": "array", "items": {"type": "object", "properties": {"action": {"type": "string"}, "rationale_metric_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["action", "rationale_metric_ids"], "additionalProperties": False}},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "needs_review": {"type": "boolean"},
                },
                "required": ["summary", "evidence", "drivers", "assumptions", "recommended_actions", "confidence", "needs_review"],
                "additionalProperties": False,
            },
        },
    }

    def __init__(self, base_url: str, credential_reference: str, secret_provider: SecretProvider, model: str = "gpt-5-mini") -> None:
        if not base_url.startswith("https://"):
            raise ReportFlowError("AI Copilot provider endpoint must use HTTPS.")
        self.base_url, self.credential_reference, self.secret_provider, self.model = base_url.rstrip("/"), credential_reference, secret_provider, model

    def generate(self, request: GovernedCopilotRequest) -> dict[str, Any]:
        secret = self.secret_provider.resolve(self.credential_reference)
        if not secret:
            raise ReportFlowError("AI Copilot secret reference resolved to an empty value.")
        try:
            from openai import OpenAI  # type: ignore[import-not-found]
        except ImportError as error:
            raise ReportFlowError("AI Copilot provider requires optional dependency openai.") from error
        messages = [
            {"role": "system", "content": "You are ReportFlow Copilot. Use only the supplied deterministic evidence. Never invent numbers, sources, filters, definitions, or citations. Return JSON only."},
            {"role": "user", "content": json.dumps(request.prompt_payload, ensure_ascii=False)},
        ]
        try:
            response = OpenAI(base_url=self.base_url, api_key=secret).chat.completions.create(
                model=self.model, messages=messages, response_format=self.RESPONSE_SCHEMA, max_completion_tokens=1400,
            )
            content = response.choices[0].message.content
            if not content:
                raise ReportFlowError("AI Copilot provider returned an empty response.")
            return dict(json.loads(content))
        except ReportFlowError:
            raise
        except Exception as error:
            raise ReportFlowError("AI Copilot provider request failed without disclosing provider details.") from error
