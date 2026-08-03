"""Research-goal input shared by the CLI, workflow, and audit output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return tuple(result)


def parse_goal_line(value: str) -> tuple[str, ...]:
    """Split interactive input on semicolons, preserving commas in chemical names."""

    return _unique(value.replace("；", ";").split(";"))


@dataclass(frozen=True)
class ResearchGoal:
    compounds: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    pathways: tuple[str, ...] = ()
    strength: int = 80

    @property
    def active(self) -> bool:
        return bool(self.compounds or self.classes or self.pathways)

    def as_dict(self) -> dict[str, Any]:
        return {
            "compounds": list(self.compounds),
            "classes": list(self.classes),
            "pathways": list(self.pathways),
            "strength": self.strength,
        }

    @classmethod
    def create(
        cls,
        compounds: Iterable[str] = (),
        classes: Iterable[str] = (),
        pathways: Iterable[str] = (),
        strength: int = 80,
    ) -> "ResearchGoal":
        if not 0 <= int(strength) <= 100:
            raise ValueError("preference strength must be between 0 and 100")
        return cls(_unique(compounds), _unique(classes), _unique(pathways), int(strength))

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ResearchGoal":
        data = value or {}
        return cls.create(
            data.get("compounds") or (),
            data.get("classes") or (),
            data.get("pathways") or (),
            int(data.get("strength", 80)),
        )

    def describe(self) -> str:
        if not self.active:
            return "none (standard conservative matching)"
        parts = []
        if self.compounds:
            parts.append(f"compounds={'; '.join(self.compounds)}")
        if self.classes:
            parts.append(f"classes={'; '.join(self.classes)}")
        if self.pathways:
            parts.append(f"pathways={'; '.join(self.pathways)}")
        parts.append(f"preference_strength={self.strength}/100")
        return "; ".join(parts)
