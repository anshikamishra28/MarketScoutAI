"""Internal, domain-neutral representation of comparison interpretation."""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
import math
from typing import Any

from models.comparison import ComparisonRequest


class ComparisonIntentState(str, Enum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"


class Provenance(str, Enum):
    USER_PROVIDED = "user_provided"
    PROPOSED = "proposed"
    USER_CONFIRMED = "user_confirmed"


@dataclass
class InterpretationIssue:
    """An unresolved or ambiguous part of a comparison request."""

    code: str
    target: str
    message: str
    candidates: list[Any] = field(default_factory=list)
    clarification_question: str | None = None

    def __post_init__(self) -> None:
        for name in ("code", "target", "message"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            setattr(self, name, value.strip())
        if self.target not in {"request", "entity", "attribute", "source", "identifier"}:
            raise ValueError("target must be request, entity, attribute, source, or identifier")
        if not isinstance(self.candidates, list):
            raise ValueError("candidates must be a list")
        self.candidates = [_json_value(value) for value in self.candidates]
        if self.clarification_question is not None:
            if not isinstance(self.clarification_question, str):
                raise ValueError("clarification_question must be a string or None")
            self.clarification_question = self.clarification_question.strip() or None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "target": self.target,
            "message": self.message,
            "candidates": [_json_value(value) for value in self.candidates],
            "clarification_question": self.clarification_question,
        }


@dataclass
class ComparisonIntent:
    """A draft execution request plus interpretation state and provenance."""

    request: ComparisonRequest
    state: ComparisonIntentState | str
    unresolved: list[InterpretationIssue] = field(default_factory=list)
    provenance: dict[str, Provenance | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.request, ComparisonRequest):
            raise ValueError("request must be a ComparisonRequest")
        try:
            self.state = ComparisonIntentState(self.state)
        except (TypeError, ValueError) as exc:
            raise ValueError("state must be ready or needs_clarification") from exc
        if not isinstance(self.unresolved, list):
            raise ValueError("unresolved must be a list")
        self.unresolved = [
            InterpretationIssue(**issue) if isinstance(issue, dict) else issue
            for issue in self.unresolved
        ]
        if not all(isinstance(issue, InterpretationIssue) for issue in self.unresolved):
            raise ValueError("unresolved must contain InterpretationIssue values")
        if self.state is ComparisonIntentState.READY and self.unresolved:
            raise ValueError("ready intent cannot contain unresolved issues")
        if self.state is ComparisonIntentState.NEEDS_CLARIFICATION and not self.unresolved:
            raise ValueError("needs_clarification intent must contain an unresolved issue")
        if not isinstance(self.provenance, dict):
            raise ValueError("provenance must be an object")
        normalized = {}
        for path, origin in self.provenance.items():
            if not isinstance(path, str) or not path.strip():
                raise ValueError("provenance paths must be non-empty strings")
            try:
                normalized[path.strip()] = Provenance(origin)
            except (TypeError, ValueError) as exc:
                raise ValueError("provenance values must be user_provided, proposed, or user_confirmed") from exc
        self.provenance = normalized

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "state": self.state.value,
            "unresolved": [issue.to_dict() for issue in self.unresolved],
            "provenance": {path: origin.value for path, origin in self.provenance.items()},
        }


def _json_value(value: Any) -> Any:
    """Serialize the JSON-compatible values used by comparison requests."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("candidate numbers must be finite")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _json_value(item) for key, item in value.items()}
    raise ValueError("candidate values must be JSON-compatible")
