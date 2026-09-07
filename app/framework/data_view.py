"""Renderer-neutral filtering and sorting for keyed structured records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


def _key(value: object, *, field: str = "key") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


class SortDirection(str, Enum):
    ASCENDING = "ascending"
    DESCENDING = "descending"


@dataclass(frozen=True)
class SortTerm:
    field: str
    direction: SortDirection = SortDirection.ASCENDING

    def __init__(self, field: object, direction: SortDirection | str = SortDirection.ASCENDING):
        object.__setattr__(self, "field", _key(field, field="sort field"))
        try:
            resolved = SortDirection(str(getattr(direction, "value", direction)))
        except ValueError as exc:
            raise ValueError("sort direction must be ascending or descending") from exc
        object.__setattr__(self, "direction", resolved)


@dataclass(frozen=True)
class DataRecord:
    key: str
    values: Mapping[str, object]

    def __init__(self, key: object, values: Mapping[str, object]):
        if not isinstance(values, Mapping):
            raise TypeError("data record values must be a mapping")
        object.__setattr__(self, "key", _key(key, field="record key"))
        object.__setattr__(self, "values", dict(values))


@dataclass(frozen=True)
class DataViewResult:
    keys: tuple[str, ...]
    total_count: int
    visible_count: int


class DataView:
    """Explicit query/sort projection over keyed records.

    Search matching is case-insensitive text containment over selected fields.
    Choice filters use exact value equality.  Multi-column sorting follows the
    declared term priority and uses Python's stable sort.
    """

    def __init__(self):
        self.search_text = ""
        self.search_fields: tuple[str, ...] = ()
        self.choice_filters: dict[str, frozenset[object]] = {}
        self.sort_terms: tuple[SortTerm, ...] = ()

    def set_search(self, text: object, fields: Iterable[object]) -> None:
        self.search_text = str(text or "").strip().casefold()
        self.search_fields = tuple(_key(field, field="search field") for field in fields)

    def set_choice_filter(self, field: object, values: Iterable[object] | None) -> None:
        resolved = _key(field, field="filter field")
        if values is None:
            self.choice_filters.pop(resolved, None)
            return
        accepted = frozenset(values)
        if accepted:
            self.choice_filters[resolved] = accepted
        else:
            self.choice_filters.pop(resolved, None)

    def clear_filters(self) -> None:
        self.search_text = ""
        self.search_fields = ()
        self.choice_filters.clear()

    def set_sort(self, terms: Iterable[SortTerm]) -> None:
        resolved = tuple(terms)
        if not all(isinstance(term, SortTerm) for term in resolved):
            raise TypeError("sort terms must be SortTerm instances")
        self.sort_terms = resolved

    def _matches(self, record: DataRecord) -> bool:
        if self.search_text:
            fields = self.search_fields or tuple(record.values)
            if not any(
                self.search_text in str(record.values.get(field, "")).casefold()
                for field in fields
            ):
                return False
        for field, accepted in self.choice_filters.items():
            if record.values.get(field) not in accepted:
                return False
        return True

    @staticmethod
    def _sort_value(value: object):
        if value is None:
            return (1, "")
        if isinstance(value, bool):
            return (0, int(value))
        if isinstance(value, (int, float)):
            return (0, value)
        if isinstance(value, tuple):
            return (0, tuple(DataView._sort_value(item) for item in value))
        return (0, str(value).casefold())

    def project(self, records: Iterable[DataRecord]) -> DataViewResult:
        resolved = tuple(records)
        if not all(isinstance(record, DataRecord) for record in resolved):
            raise TypeError("data view records must be DataRecord instances")
        keys = tuple(record.key for record in resolved)
        if len(set(keys)) != len(keys):
            raise ValueError("data view record keys must be unique")

        visible = [record for record in resolved if self._matches(record)]
        for term in reversed(self.sort_terms):
            visible.sort(
                key=lambda record, field=term.field: self._sort_value(record.values.get(field)),
                reverse=term.direction is SortDirection.DESCENDING,
            )
        return DataViewResult(
            keys=tuple(record.key for record in visible),
            total_count=len(resolved),
            visible_count=len(visible),
        )
