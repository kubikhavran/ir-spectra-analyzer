"""Dialog for managing the reference spectrum library."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.reference_import import BatchImportSummary, ReferenceImportService
from app.reference_library_service import ReferenceLibraryService, ReferenceSearchOutcome
from core.spectrum import Spectrum
from matching.quality import match_quality_label
from storage.database import Database


class _SimilarityTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem variant that sorts by numeric similarity score."""

    def __init__(self, text: str, score: float | None) -> None:
        super().__init__(text)
        self._score = score

    def __lt__(self, other: object) -> bool:
        if isinstance(other, _SimilarityTableWidgetItem):
            left = -1.0 if self._score is None else self._score
            right = -1.0 if other._score is None else other._score
            return left < right
        return super().__lt__(other)


class ReferenceLibraryDialog(QDialog):
    """Dialog for viewing, renaming, and deleting reference spectra."""

    def __init__(
        self,
        db: Database,
        parent=None,
        library_service: ReferenceLibraryService | None = None,
        import_service: ReferenceImportService | None = None,
        current_spectrum: Spectrum | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._library_service = library_service or ReferenceLibraryService(db)
        self._import_service = import_service or ReferenceImportService(db)
        self._current_spectrum = current_spectrum
        self._project_library_folder = self._library_service.discover_project_library_folder()
        self._refs: list[dict] = []  # currently displayed (after filters)
        self._refs_all: list[dict] = []  # full unfiltered list from DB
        self._similarity_by_ref_id: dict[int, float] = {}
        self._pg = None
        self._preview_plot = None
        self._preview_curve = None
        self._current_spectrum_curve = None
        self._preview_placeholder = None
        self.setWindowTitle("Reference Library")
        self.setMinimumSize(820, 520)
        self._setup_ui()
        self._load_data()

    def _setup_ui(self) -> None:
        """Build the dialog layout."""
        root_layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # --- Left: filters + table ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(self._build_filter_panel())

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Similarity", "Quality", "Description", "Source", "Y Unit", "Created At"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        left_layout.addWidget(self._table)
        splitter.addWidget(left_widget)

        # --- Right: preview ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 4, 4, 4)

        self._preview_label = QLabel("Select a row to preview")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._preview_label.setWordWrap(True)
        self._create_preview_plot_widget(right_layout)

        self._show_current_spectrum_cb = QCheckBox("Show current spectrum")
        self._show_current_spectrum_cb.setEnabled(self._current_spectrum is not None)
        self._show_current_spectrum_cb.stateChanged.connect(self._on_show_current_spectrum_toggled)
        right_layout.addWidget(self._show_current_spectrum_cb)

        right_layout.addWidget(self._preview_label)

        self._library_label = QLabel(self._project_library_status_text())
        self._library_label.setWordWrap(True)
        self._library_label.setStyleSheet("color: gray; font-size: 9pt;")
        right_layout.addWidget(self._library_label)

        self._search_label = QLabel(self._search_status_text())
        self._search_label.setWordWrap(True)
        self._search_label.setStyleSheet("color: gray; font-size: 9pt;")
        right_layout.addWidget(self._search_label)

        right_layout.addStretch()

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        root_layout.addWidget(splitter)

        # --- Bottom buttons ---
        btn_layout = QHBoxLayout()

        self._rename_btn = QPushButton("Rename")
        self._rename_btn.setEnabled(False)
        self._rename_btn.clicked.connect(self._on_rename)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)

        self._choose_library_folder_btn = QPushButton("Choose Folder...")
        self._choose_library_folder_btn.clicked.connect(self._on_choose_library_folder)

        self._sync_project_library_btn = QPushButton("Sync Folder")
        self._sync_project_library_btn.setEnabled(self._project_library_folder is not None)
        self._sync_project_library_btn.clicked.connect(self._on_sync_project_library)

        self._import_file_btn = QPushButton("Import File...")
        self._import_file_btn.clicked.connect(self._on_import_files)

        self._find_similar_btn = QPushButton("Find Similar to Current Spectrum")
        self._find_similar_btn.setEnabled(
            self._current_spectrum is not None and self._project_library_folder is not None
        )
        self._find_similar_btn.clicked.connect(self._on_find_similar)

        self._clear_search_btn = QPushButton("Show All")
        self._clear_search_btn.setEnabled(False)
        self._clear_search_btn.clicked.connect(self._on_clear_similarity_search)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        btn_layout.addWidget(self._choose_library_folder_btn)
        btn_layout.addWidget(self._sync_project_library_btn)
        btn_layout.addWidget(self._import_file_btn)
        btn_layout.addWidget(self._find_similar_btn)
        btn_layout.addWidget(self._clear_search_btn)
        btn_layout.addWidget(self._rename_btn)
        btn_layout.addWidget(self._delete_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)

        root_layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Filter panel
    # ------------------------------------------------------------------

    def _build_filter_panel(self) -> QGroupBox:
        """Build the collapsible filter bar above the table."""
        box = QGroupBox("Filters")
        box.setStyleSheet("QGroupBox { font-size: 9pt; }")
        form = QFormLayout(box)
        form.setContentsMargins(6, 4, 6, 4)
        form.setSpacing(4)

        # Name search
        self._filter_name = QLineEdit()
        self._filter_name.setPlaceholderText("e.g. PAR or KLH")
        self._filter_name.setClearButtonEnabled(True)
        self._filter_name.textChanged.connect(self._on_filter_changed)
        form.addRow("Name contains:", self._filter_name)

        # Y-unit filter
        self._filter_yunit = QComboBox()
        self._filter_yunit.addItems(["All", "Absorbance", "Transmittance", "%Transmittance"])
        self._filter_yunit.currentIndexChanged.connect(self._on_filter_changed)
        form.addRow("Y unit:", self._filter_yunit)

        # Date preset
        date_row = QHBoxLayout()
        self._filter_date_preset = QComboBox()
        self._filter_date_preset.addItems(
            [
                "All time",
                "Last 7 days",
                "Last 30 days",
                "Last 3 months",
                "Last 6 months",
                "Last year",
                "Custom range…",
            ]
        )
        self._filter_date_preset.currentIndexChanged.connect(self._on_date_preset_changed)
        date_row.addWidget(self._filter_date_preset)
        date_row.addStretch()
        form.addRow("Imported:", date_row)

        # Custom date range (hidden by default)
        self._custom_date_widget = QWidget()
        custom_row = QHBoxLayout(self._custom_date_widget)
        custom_row.setContentsMargins(0, 0, 0, 0)
        custom_row.setSpacing(4)
        custom_row.addWidget(QLabel("From:"))
        self._filter_date_from = QDateEdit()
        self._filter_date_from.setCalendarPopup(True)
        self._filter_date_from.setDate(QDate.currentDate().addMonths(-3))
        self._filter_date_from.dateChanged.connect(self._on_filter_changed)
        custom_row.addWidget(self._filter_date_from)
        custom_row.addWidget(QLabel("To:"))
        self._filter_date_to = QDateEdit()
        self._filter_date_to.setCalendarPopup(True)
        self._filter_date_to.setDate(QDate.currentDate())
        self._filter_date_to.dateChanged.connect(self._on_filter_changed)
        custom_row.addWidget(self._filter_date_to)
        custom_row.addStretch()
        self._custom_date_widget.setVisible(False)
        form.addRow("", self._custom_date_widget)

        return box

    def _on_date_preset_changed(self) -> None:
        """Show/hide custom date widgets and re-apply filters."""
        is_custom = self._filter_date_preset.currentText() == "Custom range…"
        self._custom_date_widget.setVisible(is_custom)
        self._on_filter_changed()

    def _on_filter_changed(self) -> None:
        """Re-apply active filters and refresh the table."""
        self._populate_table(self._apply_filters(self._refs_all))

    def _apply_filters(self, refs: list[dict]) -> list[dict]:
        """Return the subset of refs that pass all active filters."""
        name_query = self._filter_name.text().strip().lower()
        yunit_filter = self._filter_yunit.currentText()
        date_preset = self._filter_date_preset.currentText()

        # Compute date boundary
        now = datetime.now()
        date_from: datetime | None = None
        date_to: datetime | None = None
        if date_preset == "Last 7 days":
            date_from = now - timedelta(days=7)
        elif date_preset == "Last 30 days":
            date_from = now - timedelta(days=30)
        elif date_preset == "Last 3 months":
            date_from = now - timedelta(days=91)
        elif date_preset == "Last 6 months":
            date_from = now - timedelta(days=182)
        elif date_preset == "Last year":
            date_from = now - timedelta(days=365)
        elif date_preset == "Custom range…":
            qfrom = self._filter_date_from.date()
            qto = self._filter_date_to.date()
            date_from = datetime(qfrom.year(), qfrom.month(), qfrom.day())
            date_to = datetime(qto.year(), qto.month(), qto.day(), 23, 59, 59)

        result = []
        for ref in refs:
            # Name filter
            if name_query and name_query not in str(ref.get("name", "")).lower():
                continue

            # Y-unit filter
            if yunit_filter != "All":
                ref_unit = str(ref.get("y_unit", "")).strip()
                if ref_unit.lower() != yunit_filter.lower():
                    continue

            # Date filter
            if date_from is not None or date_to is not None:
                created_str = str(ref.get("created_at", ""))
                try:
                    # SQLite format: "2024-01-15 12:34:56" or "2024-01-15T12:34:56"
                    created_str = created_str.replace("T", " ")
                    created = datetime.strptime(created_str[:19], "%Y-%m-%d %H:%M:%S")
                except (ValueError, IndexError):
                    created = None
                if created is not None:
                    if date_from is not None and created < date_from:
                        continue
                    if date_to is not None and created > date_to:
                        continue

            result.append(ref)

        return result

    # ------------------------------------------------------------------
    # Table population (split from _load_data for filter reuse)
    # ------------------------------------------------------------------

    def _populate_table(self, refs: list[dict]) -> None:
        """Fill the table widget from a (pre-filtered) list of reference dicts."""
        sorted_refs = sorted(refs, key=self._sort_key_for_ref)
        self._refs = sorted_refs

        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        for ref in sorted_refs:
            row = self._table.rowCount()
            self._table.insertRow(row)

            name_item = QTableWidgetItem(ref["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, ref["id"])
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, self._similarity_item_for_ref(ref))
            self._table.setItem(row, 2, QTableWidgetItem(self._quality_text_for_ref(ref)))
            self._table.setItem(row, 3, QTableWidgetItem(ref.get("description", "")))
            self._table.setItem(row, 4, QTableWidgetItem(ref.get("source", "")))
            self._table.setItem(row, 5, QTableWidgetItem(ref.get("y_unit", "")))
            self._table.setItem(row, 6, QTableWidgetItem(ref.get("created_at", "")))

        self._table.setSortingEnabled(True)
        if self._similarity_by_ref_id:
            self._table.sortItems(1, Qt.SortOrder.DescendingOrder)
        else:
            self._table.sortItems(0, Qt.SortOrder.AscendingOrder)
        self._table.resizeColumnsToContents()
        self._table.clearSelection()
        self._preview_label.setText("Select a row to preview")
        self._show_empty_preview_plot()
        self._update_button_state()

    def _load_data(self) -> None:
        """Fetch all reference spectra from DB and populate the table."""
        self._project_library_folder = self._library_service.discover_project_library_folder()
        self._refs_all = self._library_service.get_library_references()

        self._populate_table(self._apply_filters(self._refs_all))

        self._library_label.setText(self._project_library_status_text())
        if self._similarity_by_ref_id:
            self._search_label.setText(
                self._search_status_text(match_count=len(self._similarity_by_ref_id))
            )
        else:
            self._search_label.setText(self._search_status_text())

    def _selected_ref_id(self) -> int | None:
        """Return the DB id of the currently selected row, or None."""
        selected = self._table.selectedItems()
        if not selected:
            return None
        row = self._table.currentRow()
        item = self._table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _selected_ref(self) -> dict | None:
        """Return the full dict for the selected reference, or None."""
        ref_id = self._selected_ref_id()
        if ref_id is None:
            return None
        return next((r for r in self._refs if r["id"] == ref_id), None)

    def _on_selection_changed(self) -> None:
        """Update preview and button states when the table selection changes."""
        self._update_button_state()
        ref = self._selected_ref()
        if ref is None:
            self._preview_label.setText("Select a row to preview")
            self._show_empty_preview_plot()
            return

        self._show_reference_preview(ref)
        n_points = len(ref.get("wavenumbers", []))
        text = (
            f"Name: {ref['name']}\n"
            f"Similarity: {self._similarity_text_for_ref(ref)}\n"
            f"Quality: {self._quality_text_for_ref(ref)}\n"
            f"Description: {ref.get('description', '')}\n"
            f"Source: {ref.get('source', '')}\n"
            f"Y Unit: {ref.get('y_unit', '')}\n"
            f"Created: {ref.get('created_at', '')}\n"
            f"Points: {n_points}"
        )
        self._preview_label.setText(text)

    def _update_button_state(self) -> None:
        """Enable/disable action buttons based on whether a row is selected."""
        has_selection = self._selected_ref_id() is not None
        self._rename_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)
        self._clear_search_btn.setEnabled(bool(self._similarity_by_ref_id))
        self._sync_project_library_btn.setEnabled(self._project_library_folder is not None)
        self._find_similar_btn.setEnabled(
            self._current_spectrum is not None and self._project_library_folder is not None
        )

    def _on_choose_library_folder(self) -> None:
        """Let the user pick the active reference-library folder."""
        start_dir = ""
        if self._project_library_folder is not None:
            start_dir = str(self._project_library_folder)

        chosen = QFileDialog.getExistingDirectory(
            self,
            "Choose Reference Library Folder",
            start_dir,
        )
        if not chosen:
            return

        try:
            folder = self._library_service.set_selected_library_folder(Path(chosen))
            summary = self._library_service.import_project_library()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Reference Folder Error",
                f"Failed to use the selected folder:\n{exc}",
            )
            return

        self._similarity_by_ref_id.clear()
        self._project_library_folder = folder
        self._load_data()
        self._library_label.setText(self._project_library_status_text(summary))

    def _on_sync_project_library(self) -> None:
        """Import missing spectra from the active reference-library folder."""
        try:
            summary = self._library_service.import_project_library()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Reference Folder Sync Error",
                f"Failed to sync reference folder:\n{exc}",
            )
            return

        self._project_library_folder = self._library_service.discover_project_library_folder()
        if summary is None:
            self._library_label.setText(self._project_library_status_text())
            return

        self._load_data()
        self._library_label.setText(self._project_library_status_text(summary))

    def _on_import_files(self) -> None:
        """Import one or more `.spa` files directly into the reference library."""
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Reference Spectrum",
            "" if self._project_library_folder is None else str(self._project_library_folder),
            "OMNIC SPA Files (*.spa *.SPA);;All Files (*)",
        )
        if not paths:
            return

        imported = 0
        failures: list[str] = []
        active_folder = (
            self._project_library_folder.resolve() if self._project_library_folder else None
        )
        for raw_path in paths:
            path = Path(raw_path)
            if active_folder is not None:
                try:
                    path.resolve().relative_to(active_folder)
                except ValueError:
                    failures.append(f"{path.name}: file is outside the active reference folder")
                    continue
            try:
                self._import_service.import_reference_file(path, prefer_filename=True)
                imported += 1
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{path.name}: {exc}")

        self._load_data()
        summary = f"Imported: {imported}\nFailed: {len(failures)}"
        if failures:
            summary += "\n\n" + "\n".join(failures[:3])
        QMessageBox.information(self, "Reference Import Summary", summary)

    def _on_find_similar(self) -> None:
        """Rank the reference library by similarity to the current spectrum."""
        if self._project_library_folder is None:
            self._search_label.setText(self._search_status_text())
            return
        if self._current_spectrum is None:
            self._search_label.setText(self._search_status_text())
            return

        try:
            outcome = self._library_service.search_spectrum(
                self._current_spectrum,
                top_n=None,
                auto_import_project_library=True,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Similarity Search Error",
                f"Failed to search reference library:\n{exc}",
            )
            return

        self._similarity_by_ref_id = {result.ref_id: result.score for result in outcome.results}
        self._project_library_folder = (
            outcome.library_folder or self._library_service.discover_project_library_folder()
        )
        self._load_data()
        self._apply_search_outcome_status(outcome)

    def _on_clear_similarity_search(self) -> None:
        """Return the library table to its default alphabetical view."""
        self._similarity_by_ref_id.clear()
        self._load_data()

    def _on_delete(self) -> None:
        """Confirm and delete the selected reference spectrum."""
        ref = self._selected_ref()
        if ref is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete Reference",
            f'Delete reference spectrum "{ref["name"]}"?\nThis cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._db.delete_reference_spectrum(ref["id"])
        self._preview_label.setText("Select a row to preview")
        self._load_data()

    def _on_rename(self) -> None:
        """Prompt for a new name and rename the selected reference spectrum."""
        ref = self._selected_ref()
        if ref is None:
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Rename Reference",
            "New name:",
            text=ref["name"],
        )
        if not ok or not new_name.strip():
            return

        self._db.rename_reference_spectrum(ref["id"], new_name.strip())
        self._load_data()

    def _project_library_status_text(
        self,
        summary: BatchImportSummary | None = None,
    ) -> str:
        """Return status text for the active reference-library folder."""
        folder = self._project_library_folder
        if folder is None:
            return "Reference library folder: not selected"

        text = f"Reference library folder: {self._display_path(folder)}"
        if summary is not None:
            text += (
                f"\nLast sync: Imported {summary.imported} | "
                f"Skipped {summary.skipped} | Failed {summary.failed}"
            )
        return text

    @staticmethod
    def _display_path(path: Path) -> str:
        """Show a readable path in the dialog without hard-coding absolute roots."""
        try:
            return str(path.relative_to(Path.cwd()))
        except ValueError:
            return str(path)

    def _search_status_text(
        self,
        *,
        match_count: int | None = None,
        imported_summary: BatchImportSummary | None = None,
    ) -> str:
        """Return status text for the similarity-search workflow."""
        if self._project_library_folder is None:
            return "Similarity search: choose a reference folder first"
        if self._current_spectrum is None:
            return "Similarity search: load a spectrum to rank the library"
        if match_count is None:
            return "Similarity search: not run yet"

        text = f"Similarity search: ranked {match_count} library spectra"
        if imported_summary is not None and imported_summary.imported > 0:
            text += f"\nFolder sync imported: {imported_summary.imported}"
        return text

    def _apply_search_outcome_status(self, outcome: ReferenceSearchOutcome) -> None:
        """Update the sidebar labels after a similarity search run."""
        if outcome.imported_summary is not None:
            self._library_label.setText(self._project_library_status_text(outcome.imported_summary))
        self._search_label.setText(
            self._search_status_text(
                match_count=len(outcome.results),
                imported_summary=outcome.imported_summary,
            )
        )

    def _sort_key_for_ref(self, ref: dict) -> tuple[float, str]:
        """Sort by similarity search score when present, otherwise alphabetically."""
        ref_id = int(ref["id"])
        score = self._similarity_by_ref_id.get(ref_id)
        if score is None:
            return (1.0, str(ref["name"]).casefold())
        return (-score, str(ref["name"]).casefold())

    def _similarity_item_for_ref(self, ref: dict) -> QTableWidgetItem:
        """Create the similarity column item for a reference row."""
        score = self._similarity_by_ref_id.get(int(ref["id"]))
        text = self._similarity_text_for_ref(ref)
        item = _SimilarityTableWidgetItem(text, score)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _similarity_text_for_ref(self, ref: dict) -> str:
        """Return a display string for the current similarity score of a reference."""
        score = self._similarity_by_ref_id.get(int(ref["id"]))
        if score is None:
            return "—"
        return f"{score * 100:.1f}%"

    def _quality_text_for_ref(self, ref: dict) -> str:
        """Return the quality band for the current similarity score of a reference."""
        score = self._similarity_by_ref_id.get(int(ref["id"]))
        if score is None:
            return "—"
        return match_quality_label(score)

    def _create_preview_plot_widget(self, layout: QVBoxLayout) -> None:
        """Create the miniature spectrum preview plot in the right-side panel."""
        import pyqtgraph as pg  # noqa: PLC0415

        self._pg = pg
        self._preview_plot = pg.PlotWidget(background="w")
        self._preview_plot.setMinimumHeight(200)
        self._preview_plot.setMenuEnabled(False)
        self._preview_plot.setMouseEnabled(x=False, y=False)
        self._preview_plot.hideButtons()
        self._preview_plot.invertX(True)
        self._preview_plot.showGrid(x=False, y=False, alpha=0.0)
        self._preview_plot.setLabel("bottom", "Wavenumber (cm⁻¹)")
        self._preview_plot.setLabel("left", "")
        for axis in ("bottom", "left"):
            axis_item = self._preview_plot.getAxis(axis)
            axis_item.setPen(pg.mkPen(color="k", width=1))
            axis_item.setTextPen(pg.mkPen(color="k"))
        self._preview_curve = self._preview_plot.plot(pen=pg.mkPen("k", width=1))
        self._current_spectrum_curve = self._preview_plot.plot(
            pen=pg.mkPen(color=(0, 100, 200, 160), width=1.5)
        )
        self._current_spectrum_curve.setVisible(False)
        self._preview_placeholder = pg.TextItem(
            "Select a row to preview",
            color="#666666",
            anchor=(0.5, 0.5),
        )
        self._preview_plot.addItem(self._preview_placeholder)
        layout.addWidget(self._preview_plot)
        self._show_empty_preview_plot()

    def _show_empty_preview_plot(self) -> None:
        """Render an empty preview plot with placeholder text."""
        if self._preview_plot is None or self._preview_curve is None:
            return
        self._preview_curve.setData([], [])
        if self._current_spectrum_curve is not None:
            self._current_spectrum_curve.setData([], [])
            self._current_spectrum_curve.setVisible(False)
        if self._preview_placeholder is not None:
            self._preview_placeholder.setVisible(True)
            self._preview_placeholder.setPos(2200.0, 0.5)
        self._preview_plot.setXRange(400.0, 4000.0, padding=0.0)
        self._preview_plot.setYRange(0.0, 1.0, padding=0.0)

    def _on_show_current_spectrum_toggled(self) -> None:
        """Update the current-spectrum overlay curve when the checkbox changes."""
        ref = self._selected_ref()
        if ref is not None:
            self._show_reference_preview(ref)
        elif self._current_spectrum_curve is not None:
            self._current_spectrum_curve.setData([], [])
            self._current_spectrum_curve.setVisible(False)

    def _show_reference_preview(self, ref: dict) -> None:
        """Render the selected reference spectrum into the miniature preview plot."""
        import numpy as np  # noqa: PLC0415

        if self._preview_plot is None or self._preview_curve is None:
            return
        if self._preview_placeholder is not None:
            self._preview_placeholder.setVisible(False)

        show_current = (
            self._current_spectrum is not None
            and self._current_spectrum_curve is not None
            and self._show_current_spectrum_cb.isChecked()
        )

        if show_current:
            # Normalize both curves to 0–1 range for visual comparison
            ref_y = np.asarray(ref["intensities"], dtype=float)
            ref_max = np.max(np.abs(ref_y))
            norm_ref_y = ref_y / ref_max if ref_max > 0 else ref_y
            self._preview_curve.setData(x=ref["wavenumbers"], y=norm_ref_y)

            cur_y = np.asarray(self._current_spectrum.intensities, dtype=float)
            cur_max = np.max(np.abs(cur_y))
            norm_cur_y = cur_y / cur_max if cur_max > 0 else cur_y
            self._current_spectrum_curve.setData(x=self._current_spectrum.wavenumbers, y=norm_cur_y)
            self._current_spectrum_curve.setVisible(True)
        else:
            self._preview_curve.setData(x=ref["wavenumbers"], y=ref["intensities"])
            if self._current_spectrum_curve is not None:
                self._current_spectrum_curve.setData([], [])
                self._current_spectrum_curve.setVisible(False)

        self._preview_plot.autoRange()
