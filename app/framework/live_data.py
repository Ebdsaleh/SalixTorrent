"""Renderer-neutral live table and categorical state-grid contracts.

These provisional contracts cover the kind of high-frequency structured data
already used by monitoring, diagnostics and transfer views.  Data identity and
change detection live in the framework; concrete table/canvas widgets stay in
presentation adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable


RGBA = tuple[int, int, int, int]


def _key(value: object, *, field: str = "key") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


def _rgba(value: object | None, *, field: str) -> RGBA | None:
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise TypeError(f"{field} must be an RGB/RGBA iterable")
    items = tuple(value)
    if len(items) not in {3, 4}:
        raise ValueError(f"{field} must contain 3 or 4 channels")
    channels: list[int] = []
    for channel in items:
        if isinstance(channel, bool):
            raise TypeError(f"{field} channels must be integers")
        try:
            number = int(channel)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"{field} channels must be integers") from exc
        if number < 0 or number > 255:
            raise ValueError(f"{field} channels must be between 0 and 255")
        channels.append(number)
    if len(channels) == 3:
        channels.append(255)
    return tuple(channels)  # type: ignore[return-value]


@dataclass(frozen=True)
class TableColumnSpec:
    key: str
    label: str
    width_mode: str = "stretch"
    width: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _key(self.key, field="table column key"))
        object.__setattr__(self, "label", str(self.label))
        mode = str(self.width_mode or "stretch").strip().lower()
        if mode not in {"stretch", "fixed"}:
            raise ValueError("table column width_mode must be 'stretch' or 'fixed'")
        if isinstance(self.width, bool):
            raise TypeError("table column width must be numeric")
        try:
            width = float(self.width)
        except (TypeError, ValueError) as exc:
            raise TypeError("table column width must be numeric") from exc
        if width <= 0:
            raise ValueError("table column width must be greater than zero")
        object.__setattr__(self, "width_mode", mode)
        object.__setattr__(self, "width", width)


@dataclass(frozen=True)
class TableCell:
    text: str
    foreground: RGBA | None = None
    tooltip: str = ""

    def __init__(
        self,
        text: object = "",
        *,
        foreground: object | None = None,
        tooltip: object = "",
    ):
        object.__setattr__(self, "text", str(text))
        object.__setattr__(self, "foreground", _rgba(foreground, field="table cell foreground"))
        object.__setattr__(self, "tooltip", str(tooltip or ""))


@dataclass(frozen=True)
class TableRow:
    key: str
    cells: tuple[TableCell, ...]

    def __init__(self, key: object, cells: Iterable[TableCell | object]):
        resolved = tuple(cell if isinstance(cell, TableCell) else TableCell(cell) for cell in cells)
        object.__setattr__(self, "key", _key(key, field="table row key"))
        object.__setattr__(self, "cells", resolved)


@dataclass(frozen=True)
class TableFrame:
    rows: tuple[TableRow, ...]

    def __init__(self, rows: Iterable[TableRow]):
        resolved = tuple(rows)
        if not all(isinstance(row, TableRow) for row in resolved):
            raise TypeError("table frame rows must be TableRow instances")
        keys = tuple(row.key for row in resolved)
        if len(set(keys)) != len(keys):
            raise ValueError("table frame row keys must be unique")
        object.__setattr__(self, "rows", resolved)


@dataclass(frozen=True)
class TableColumnBinding:
    key: str
    item: object


@dataclass(frozen=True)
class TableBinding:
    table: object
    columns: tuple[TableColumnBinding, ...]

    def column_item(self, key: str) -> object:
        resolved = _key(key, field="table column key")
        for binding in self.columns:
            if binding.key == resolved:
                return binding.item
        raise KeyError(resolved)


@dataclass(frozen=True)
class TableRowBinding:
    key: str
    row: object
    cells: tuple[object, ...]
    metadata: object | None = None


@runtime_checkable
class TableHost(Protocol):
    def create_table(
        self,
        *,
        parent: object,
        columns: tuple[TableColumnSpec, ...],
        header_row: bool = True,
        resizable: bool = True,
        scroll_y: bool = True,
        height: int | float | None = None,
    ) -> TableBinding:
        ...

    def exists(self, item: object) -> bool:
        ...

    def destroy(self, item: object) -> None:
        ...

    def create_row(self, table: TableBinding, row: TableRow) -> TableRowBinding:
        ...

    def update_row(self, table: TableBinding, binding: TableRowBinding, row: TableRow) -> None:
        ...

    def destroy_row(self, table: TableBinding, binding: TableRowBinding) -> None:
        ...

    def reorder_rows(self, table: TableBinding, rows: tuple[TableRowBinding, ...]) -> None:
        ...


def _table_host_contract_errors(host: object) -> tuple[str, ...]:
    required = (
        "create_table",
        "exists",
        "destroy",
        "create_row",
        "update_row",
        "destroy_row",
        "reorder_rows",
    )
    return tuple(name for name in required if not callable(getattr(host, name, None)))


class LiveTable:
    """Keyed table coordinator that preserves stable backend rows across frames."""

    def __init__(self, host: TableHost, columns: Iterable[TableColumnSpec]):
        missing = _table_host_contract_errors(host)
        if missing:
            raise TypeError("table host does not satisfy TableHost; missing: " + ", ".join(missing))
        specs = tuple(columns)
        if not specs:
            raise ValueError("live table requires at least one column")
        if not all(isinstance(column, TableColumnSpec) for column in specs):
            raise TypeError("live table columns must be TableColumnSpec instances")
        keys = tuple(column.key for column in specs)
        if len(set(keys)) != len(keys):
            raise ValueError("live table column keys must be unique")
        self.host = host
        self.columns = specs
        self._binding: TableBinding | None = None
        self._rows: dict[str, TableRowBinding] = {}
        self._last_rows: dict[str, TableRow] = {}
        self._order: tuple[str, ...] = ()

    @property
    def binding(self) -> TableBinding | None:
        return self._binding

    @property
    def row_count(self) -> int:
        return len(self._rows)

    @property
    def row_keys(self) -> tuple[str, ...]:
        return self._order

    def row_binding(self, key: object) -> TableRowBinding | None:
        return self._rows.get(str(key))

    def build(
        self,
        *,
        parent: object,
        header_row: bool = True,
        resizable: bool = True,
        scroll_y: bool = True,
        height: int | float | None = None,
    ) -> TableBinding:
        if self._binding is not None and self.host.exists(self._binding.table):
            raise RuntimeError("live table is already built")
        binding = self.host.create_table(
            parent=parent,
            columns=self.columns,
            header_row=bool(header_row),
            resizable=bool(resizable),
            scroll_y=bool(scroll_y),
            height=height,
        )
        if not isinstance(binding, TableBinding):
            raise TypeError("table host must return a TableBinding")
        actual = tuple(column.key for column in binding.columns)
        expected = tuple(column.key for column in self.columns)
        if actual != expected:
            raise ValueError("table host returned column bindings in an unexpected shape")
        self._binding = binding
        self._rows.clear()
        self._last_rows.clear()
        self._order = ()
        return binding

    def exists(self) -> bool:
        return bool(self._binding is not None and self.host.exists(self._binding.table))

    def require_binding(self) -> TableBinding:
        if not self.exists():
            raise RuntimeError("live table is not built or its backend item is stale")
        assert self._binding is not None
        return self._binding

    def render(self, frame: TableFrame) -> None:
        if not isinstance(frame, TableFrame):
            raise TypeError("live table render requires a TableFrame")
        binding = self.require_binding()
        for row in frame.rows:
            if len(row.cells) != len(self.columns):
                raise ValueError(
                    f"table row {row.key!r} has {len(row.cells)} cells; expected {len(self.columns)}"
                )

        incoming = {row.key: row for row in frame.rows}
        for key in tuple(self._rows):
            if key not in incoming:
                self.host.destroy_row(binding, self._rows.pop(key))
                self._last_rows.pop(key, None)

        for row in frame.rows:
            current = self._rows.get(row.key)
            if current is None:
                created = self.host.create_row(binding, row)
                if not isinstance(created, TableRowBinding):
                    raise TypeError("table host must return a TableRowBinding")
                if created.key != row.key:
                    raise ValueError("table host returned a row binding with the wrong key")
                self._rows[row.key] = created
                self._last_rows[row.key] = row
            elif self._last_rows.get(row.key) != row:
                self.host.update_row(binding, current, row)
                self._last_rows[row.key] = row

        order = tuple(row.key for row in frame.rows)
        if order != self._order:
            self.host.reorder_rows(binding, tuple(self._rows[key] for key in order))
            self._order = order

    def clear(self) -> None:
        if self._binding is None:
            self._rows.clear()
            self._last_rows.clear()
            self._order = ()
            return
        for row in tuple(self._rows.values()):
            self.host.destroy_row(self._binding, row)
        self._rows.clear()
        self._last_rows.clear()
        self._order = ()

    def dispose(self) -> None:
        binding = self._binding
        if binding is not None:
            self.clear()
        self._binding = None
        if binding is not None and self.host.exists(binding.table):
            self.host.destroy(binding.table)


@dataclass(frozen=True)
class StateGridCell:
    key: str
    fill: RGBA
    border: RGBA = (35, 35, 40, 255)
    tooltip: str = ""

    def __init__(
        self,
        key: object,
        fill: object,
        *,
        border: object = (35, 35, 40, 255),
        tooltip: object = "",
    ):
        fill_value = _rgba(fill, field="state-grid fill")
        border_value = _rgba(border, field="state-grid border")
        assert fill_value is not None and border_value is not None
        object.__setattr__(self, "key", _key(key, field="state-grid cell key"))
        object.__setattr__(self, "fill", fill_value)
        object.__setattr__(self, "border", border_value)
        object.__setattr__(self, "tooltip", str(tooltip or ""))


@dataclass(frozen=True)
class StateGridFrame:
    cells: tuple[StateGridCell, ...]

    def __init__(self, cells: Iterable[StateGridCell]):
        resolved = tuple(cells)
        if not all(isinstance(cell, StateGridCell) for cell in resolved):
            raise TypeError("state-grid cells must be StateGridCell instances")
        keys = tuple(cell.key for cell in resolved)
        if len(set(keys)) != len(keys):
            raise ValueError("state-grid cell keys must be unique")
        object.__setattr__(self, "cells", resolved)


@dataclass(frozen=True)
class StateGridBinding:
    grid: object
    metadata: object | None = None


@runtime_checkable
class StateGridHost(Protocol):
    def create_state_grid(
        self,
        *,
        parent: object,
        height: int | float,
        minimum_columns: int = 24,
        maximum_columns: int = 128,
        minimum_cell_width: int | float = 7,
    ) -> StateGridBinding:
        ...

    def exists(self, item: object) -> bool:
        ...

    def destroy(self, item: object) -> None:
        ...

    def set_cells(self, grid: StateGridBinding, cells: tuple[StateGridCell, ...]) -> None:
        ...


def _state_grid_host_contract_errors(host: object) -> tuple[str, ...]:
    required = ("create_state_grid", "exists", "destroy", "set_cells")
    return tuple(name for name in required if not callable(getattr(host, name, None)))


class StateGrid:
    """Coordinator for compact categorical/state maps such as piece activity grids."""

    def __init__(self, host: StateGridHost):
        missing = _state_grid_host_contract_errors(host)
        if missing:
            raise TypeError(
                "state-grid host does not satisfy StateGridHost; missing: " + ", ".join(missing)
            )
        self.host = host
        self._binding: StateGridBinding | None = None
        self._last_frame: StateGridFrame | None = None

    @property
    def binding(self) -> StateGridBinding | None:
        return self._binding

    def build(
        self,
        *,
        parent: object,
        height: int | float,
        minimum_columns: int = 24,
        maximum_columns: int = 128,
        minimum_cell_width: int | float = 7,
    ) -> StateGridBinding:
        if self._binding is not None and self.host.exists(self._binding.grid):
            raise RuntimeError("state grid is already built")
        binding = self.host.create_state_grid(
            parent=parent,
            height=height,
            minimum_columns=minimum_columns,
            maximum_columns=maximum_columns,
            minimum_cell_width=minimum_cell_width,
        )
        if not isinstance(binding, StateGridBinding):
            raise TypeError("state-grid host must return a StateGridBinding")
        self._binding = binding
        self._last_frame = None
        return binding

    def exists(self) -> bool:
        return bool(self._binding is not None and self.host.exists(self._binding.grid))

    def require_binding(self) -> StateGridBinding:
        if not self.exists():
            raise RuntimeError("state grid is not built or its backend item is stale")
        assert self._binding is not None
        return self._binding

    def render(self, frame: StateGridFrame) -> None:
        if not isinstance(frame, StateGridFrame):
            raise TypeError("state-grid render requires a StateGridFrame")
        if frame == self._last_frame:
            return
        binding = self.require_binding()
        self.host.set_cells(binding, frame.cells)
        self._last_frame = frame

    def clear(self) -> None:
        if not self.exists():
            self._last_frame = None
            return
        self.host.set_cells(self.require_binding(), ())
        self._last_frame = StateGridFrame(())

    def dispose(self) -> None:
        binding = self._binding
        self._binding = None
        self._last_frame = None
        if binding is not None and self.host.exists(binding.grid):
            self.host.destroy(binding.grid)
