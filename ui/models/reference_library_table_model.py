"""Model/view helpers for the reference-library dialog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtWidgets import QTableView

from matching.quality import match_quality_label

COL_NAME = 0
COL_SIMILARITY = 1
COL_QUALITY = 2
COL_DESCRIPTION = 3
COL_SOURCE = 4
COL_Y_UNIT = 5
COL_CREATED_AT = 6

HEADERS = (
    "Name",
    "Similarity",
    "Quality",
    "Description",
    "Source",
    "Y Unit",
    "Created At",
)


class ReferenceLibraryTableModel(QAbstractTableModel):
    """Qt table model for the reference-library listing."""

    description_edited = Signal(int, str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._sort_column = COL_NAME
        self._sort_order = Qt.SortOrder.AscendingOrder

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is None:
            parent = QModelIndex()
        if parent.isValid():
            return 0
        return len(HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if column == COL_NAME:
                return str(row.get("name", ""))
            if column == COL_SIMILARITY:
                score = self._similarity_score(row)
                return "—" if score is None else f"{score * 100:.1f}%"
            if column == COL_QUALITY:
                score = self._similarity_score(row)
                return "—" if score is None else match_quality_label(score)
            if column == COL_DESCRIPTION:
                return str(row.get("description", ""))
            if column == COL_SOURCE:
                return str(row.get("source", ""))
            if column == COL_Y_UNIT:
                return str(row.get("y_unit", ""))
            if column == COL_CREATED_AT:
                return str(row.get("created_at", ""))

        if role == Qt.ItemDataRole.TextAlignmentRole and column == COL_SIMILARITY:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ToolTipRole and column == COL_SOURCE:
            return str(row.get("source", ""))

        if role == Qt.ItemDataRole.UserRole:
            return row.get("id")

        return None

    def flags(self, index: QModelIndex):  # noqa: D401
        """Return cell flags, keeping only the Description column editable."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if index.column() == COL_DESCRIPTION:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole):  # noqa: N802
        if (
            not index.isValid()
            or index.column() != COL_DESCRIPTION
            or role != Qt.ItemDataRole.EditRole
        ):
            return False

        row = self._rows[index.row()]
        old_description = str(row.get("description", ""))
        new_description = str(value)
        if new_description == old_description:
            return False

        row["description"] = new_description
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
        ref_id = row.get("id")
        if isinstance(ref_id, int):
            self.description_edited.emit(ref_id, new_description, old_description)
        return True

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(HEADERS)
        ):
            return HEADERS[section]
        return super().headerData(section, orientation, role)

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self._sort_column = int(column)
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(
            key=lambda row: self._sort_key(row, self._sort_column),
            reverse=order == Qt.SortOrder.DescendingOrder,
        )
        self.layoutChanged.emit()

    def set_rows(self, rows: list[dict]) -> None:
        """Replace the displayed rows and preserve the active sort mode."""
        self.beginResetModel()
        self._rows = [dict(row) for row in rows]
        self._rows.sort(
            key=lambda row: self._sort_key(row, self._sort_column),
            reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
        )
        self.endResetModel()

    def update_description(self, ref_id: int, description: str) -> None:
        """Update one row description programmatically and repaint the cell."""
        for row_index, row in enumerate(self._rows):
            if row.get("id") != ref_id:
                continue
            row["description"] = description
            index = self.index(row_index, COL_DESCRIPTION)
            self.dataChanged.emit(
                index,
                index,
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole],
            )
            break

    def row_dict(self, row_index: int) -> dict | None:
        """Return the backing row dict for a given source-model row index."""
        if row_index < 0 or row_index >= len(self._rows):
            return None
        return self._rows[row_index]

    @staticmethod
    def _similarity_score(row: dict) -> float | None:
        raw = row.get("_similarity_score")
        if raw is None:
            return None
        return float(raw)

    @classmethod
    def _sort_key(cls, row: dict, column: int):
        if column in (COL_SIMILARITY, COL_QUALITY):
            score = cls._similarity_score(row)
            return -1.0 if score is None else score
        if column == COL_DESCRIPTION:
            return str(row.get("description", "")).casefold()
        if column == COL_SOURCE:
            return str(row.get("source", "")).casefold()
        if column == COL_Y_UNIT:
            return str(row.get("y_unit", "")).casefold()
        if column == COL_CREATED_AT:
            return str(row.get("created_at", "")).casefold()
        return str(row.get("name", "")).casefold()


class ReferenceLibraryFilterProxyModel(QSortFilterProxyModel):
    """Proxy model that owns filtering and sorting for the library dialog."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._name_query = ""
        self._yunit_filter = "All"
        self._date_from: datetime | None = None
        self._date_to: datetime | None = None
        self.setDynamicSortFilter(True)

    def set_filters(
        self,
        *,
        name_query: str,
        yunit_filter: str,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> None:
        """Update active filters and invalidate the proxy rows."""
        self.beginFilterChange()
        self._name_query = name_query.strip().lower()
        self._yunit_filter = yunit_filter
        self._date_from = date_from
        self._date_to = date_to
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(  # noqa: N802
        self,
        source_row: int,
        source_parent: QModelIndex,
    ) -> bool:
        model = self.sourceModel()
        if not isinstance(model, ReferenceLibraryTableModel):
            return True
        ref = model.row_dict(source_row)
        if ref is None:
            return False

        if self._name_query and self._name_query not in str(ref.get("name", "")).lower():
            return False

        if self._yunit_filter != "All":
            ref_unit = str(ref.get("y_unit", "")).strip()
            if ref_unit.lower() != self._yunit_filter.lower():
                return False

        if self._date_from is not None or self._date_to is not None:
            created = self._parse_created_at(str(ref.get("created_at", "")))
            if created is not None:
                if self._date_from is not None and created < self._date_from:
                    return False
                if self._date_to is not None and created > self._date_to:
                    return False

        return super().filterAcceptsRow(source_row, source_parent)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if not isinstance(model, ReferenceLibraryTableModel):
            return super().lessThan(left, right)

        left_row = model.row_dict(left.row())
        right_row = model.row_dict(right.row())
        if left_row is None or right_row is None:
            return super().lessThan(left, right)

        column = left.column()
        left_key = model._sort_key(left_row, column)
        right_key = model._sort_key(right_row, column)
        if left_key == right_key:
            left_name = str(left_row.get("name", "")).casefold()
            right_name = str(right_row.get("name", "")).casefold()
            return left_name < right_name
        return left_key < right_key

    @staticmethod
    def _parse_created_at(value: str) -> datetime | None:
        raw = value.replace("T", " ").strip()
        if not raw:
            return None
        try:
            return datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
            return None


@dataclass
class _TableCellProxy:
    """Small compatibility wrapper for tests and dialog helper methods."""

    model: QAbstractTableModel | QSortFilterProxyModel
    row_value: int
    column_value: int

    def text(self) -> str:
        data = self.model.data(self.model.index(self.row_value, self.column_value))
        return "" if data is None else str(data)

    def setText(self, text: str) -> None:  # noqa: N802
        self.model.setData(
            self.model.index(self.row_value, self.column_value),
            text,
            Qt.ItemDataRole.EditRole,
        )

    def data(self, role: int):  # noqa: D401
        """Return the cell data for the requested role."""
        return self.model.data(self.model.index(self.row_value, self.column_value), role)

    def row(self) -> int:
        return self.row_value

    def column(self) -> int:
        return self.column_value


class ReferenceLibraryTableView(QTableView):
    """QTableView with a minimal compatibility surface for legacy dialog/tests."""

    itemSelectionChanged = Signal()  # noqa: N815

    def setModel(self, model) -> None:  # noqa: N802
        super().setModel(model)
        selection_model = self.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(lambda *_: self.itemSelectionChanged.emit())

    def rowCount(self) -> int:  # noqa: N802
        model = self.model()
        return 0 if model is None else model.rowCount()

    def item(self, row: int, column: int) -> _TableCellProxy | None:
        model = self.model()
        if model is None or row < 0 or column < 0:
            return None
        if row >= model.rowCount() or column >= model.columnCount():
            return None
        return _TableCellProxy(model, row, column)

    def currentRow(self) -> int:  # noqa: N802
        index = self.currentIndex()
        return index.row() if index.isValid() else -1
