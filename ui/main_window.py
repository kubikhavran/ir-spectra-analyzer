"""
MainWindow — Hlavní okno aplikace.

Zodpovědnost:
- Dockable panel layout (spectrum viewer + peak table + metadata + vibration panel)
- Menu bar a toolbar akce
- Signál-slot propojení mezi komponentami
- Koordinace workflow: otevření souboru → analýza → export

Architektonické pravidlo:
  MainWindow NIKDY neprovádí výpočty ani I/O.
  Deleguje na core modely a processing funkce.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QMetaObject, Qt, QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QUndoStack
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QTextEdit,
)

from app.report_presets import ReportPresetManager
from processing.consensus_analysis import build_consensus_analysis
from storage.database import Database
from storage.settings import Settings
from ui.consensus_panel import ConsensusPanel
from ui.functional_group_panel import FunctionalGroupPanel
from ui.metadata_panel import MetadataPanel
from ui.molecule_widget import MoleculeWidget
from ui.peak_table_widget import PeakTableWidget
from ui.spectrum_widget import SpectrumWidget
from ui.toolbar import MainToolbar
from ui.vibration_panel import VibrationPanel
from ui.vibration_text_edit import VibrationTextEditDialog

if TYPE_CHECKING:
    from core.peak import Peak
    from core.project import Project


class MainWindow(QMainWindow):
    """Main application window with dockable analysis panels.

    One window owns exactly one project. Several windows may run side by side —
    they share the database and the settings object, but every piece of document
    state (project, file path, undo stack, unsaved-change flag, match results)
    belongs to the window, so saving in one never touches another.
    """

    #: Asks the controller for another independent window. MainWindow does not
    #: create windows itself — Application owns their lifetime.
    new_window_requested = Signal()

    _MATCH_RESULTS_LIMIT = 20
    _ASSIGNMENT_TRANSFER_TOLERANCE = 8.0  # cm⁻¹ window for copying assignments

    def __init__(
        self,
        db: Database,
        settings: Settings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._settings = settings
        from app.reference_library_service import ReferenceLibraryService  # noqa: PLC0415

        self._reference_library_service = ReferenceLibraryService(db, settings=settings)
        from app.structure_preview import StructurePreviewService  # noqa: PLC0415

        # Draws a matched spectrum's saved structure on hover. Built empty and fed
        # by _refresh_saved_project_names — nothing here runs during a search.
        self._structure_preview = StructurePreviewService()
        self._project: Project | None = None
        self._current_project_path: str | None = None  # last saved/opened .irproj path
        self._recent_menu: QMenu | None = None
        self._undo_stack = QUndoStack(self)
        self._non_undo_dirty = False
        self._project_revision = 0
        self._current_match_results: list = []
        self._current_functional_group_results: list = []
        self._reference_search_thread: QThread | None = None
        self._reference_search_context: tuple[int, int, str] | None = None
        self._vibration_presets_cache: list = []
        self._molecule_widget: MoleculeWidget
        self._report_preset_manager = ReportPresetManager(settings)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize UI layout, menus, and dock panels."""
        self.setWindowTitle("IR Spectra Analyzer")
        self.setMinimumSize(1280, 800)
        self._setup_menu()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_docks()
        self._setup_statusbar()
        self._connect_signals()

        delete_sc = QShortcut(QKeySequence.StandardKey.Delete, self)
        delete_sc.activated.connect(self._on_delete_peak)

    def _setup_menu(self) -> None:
        """Create the main menu bar."""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        new_window_action = file_menu.addAction("New &Window")
        new_window_action.setShortcut("Ctrl+Shift+N")
        new_window_action.setToolTip(
            "Open a second workspace so another spectrum or project can stay open alongside this one"
        )
        new_window_action.triggered.connect(self.new_window_requested)
        file_menu.addSeparator()

        open_action = file_menu.addAction("&Open SPA...")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_file)

        open_project_action = file_menu.addAction("Open &Project...")
        open_project_action.triggered.connect(self._on_open_project)

        save_project_action = file_menu.addAction("&Save Project...")
        save_project_action.setShortcut("Ctrl+S")
        save_project_action.triggered.connect(self._on_save_project)

        self._recent_menu = file_menu.addMenu("Open &Recent")
        # Rebuilt on every open: the list lives in the shared settings, so a file
        # opened in another window has to show up here too.
        self._recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        self._rebuild_recent_menu()
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        edit_menu = menu_bar.addMenu("&Edit")
        undo_action = self._undo_stack.createUndoAction(self, "&Undo")
        undo_action.setShortcut("Ctrl+Z")
        edit_menu.addAction(undo_action)
        redo_action = self._undo_stack.createRedoAction(self, "&Redo")
        redo_action.setShortcut("Ctrl+Y")
        edit_menu.addAction(redo_action)

        database_menu = menu_bar.addMenu("&Database")
        ref_library_action = database_menu.addAction("Reference Library...")
        ref_library_action.triggered.connect(self._on_open_reference_library)
        annotated_folder_action = database_menu.addAction("Set Annotated Projects Folder...")
        annotated_folder_action.setToolTip(
            "Folder of previously analysed .irproj files used by 'Apply assignments from match'"
        )
        annotated_folder_action.triggered.connect(self._on_set_annotated_projects_folder)
        add_reference_action = database_menu.addAction("Add Current Spectrum to Reference Library")
        add_reference_action.setToolTip(
            "Make the loaded spectrum searchable by Match Spectrum without copying "
            "its file into the reference library folder"
        )
        add_reference_action.triggered.connect(self._on_add_current_spectrum_to_library)
        self._auto_register_action = database_menu.addAction(
            "Auto-add Saved Projects to Reference Library"
        )
        self._auto_register_action.setCheckable(True)
        self._auto_register_action.setChecked(self._auto_register_saved_projects())
        self._auto_register_action.setToolTip(
            "On Save Project, also store the spectrum in the reference library so the "
            "next similar sample matches it"
        )
        self._auto_register_action.toggled.connect(self._on_auto_register_toggled)
        batch_import_action = database_menu.addAction("Batch Import References...")
        batch_import_action.triggered.connect(self._on_batch_import_references)
        batch_export_action = database_menu.addAction("Batch Export PDF Reports...")
        batch_export_action.triggered.connect(self._on_batch_export_pdf)
        batch_project_action = database_menu.addAction("Batch Generate Projects...")
        batch_project_action.triggered.connect(self._on_batch_generate_projects)
        batch_project_pdf_action = database_menu.addAction("Batch Export Project PDFs...")
        batch_project_pdf_action.triggered.connect(self._on_batch_export_project_pdfs)

        # View menu — populated after docks are created
        self._view_menu = menu_bar.addMenu("&View")

        help_menu = menu_bar.addMenu("&Help")
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self._on_about)

    def _setup_toolbar(self) -> None:
        """Add the main toolbar."""
        self._toolbar = MainToolbar(self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)

        self._toolbar.tool_mode_changed.connect(self._on_tool_mode_changed)

        if self._toolbar._open_action is not None:
            self._toolbar._open_action.triggered.connect(self._on_open_file)
        if self._toolbar._export_action is not None:
            self._toolbar._export_action.triggered.connect(self._on_export)
        if self._toolbar._detect_action is not None:
            self._toolbar._detect_action.triggered.connect(self._on_detect_peaks)
        if self._toolbar._clear_peaks_action is not None:
            self._toolbar._clear_peaks_action.triggered.connect(self._on_clear_peaks)
        self._toolbar.correct_baseline.connect(self._on_correct_baseline)
        self._toolbar.arrange_labels.connect(self._on_arrange_peak_labels)
        self._toolbar.match_spectrum.connect(self._on_match_spectrum)

    def _setup_central_widget(self) -> None:
        """Set SpectrumWidget as the central widget."""
        self._spectrum_widget = SpectrumWidget(self)
        self.setCentralWidget(self._spectrum_widget)

    def _setup_docks(self) -> None:
        """Create and add the three dockable panels."""
        dock_features = (
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        # Left dock: Vibration Presets
        self._vibration_panel = VibrationPanel(db=self._db, parent=self)
        self._dock_vibration = QDockWidget("Vibration Presets", self)
        self._dock_vibration.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock_vibration.setFeatures(dock_features)
        self._dock_vibration.setWidget(self._vibration_panel)
        self._dock_vibration.setMinimumWidth(280)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._dock_vibration)

        # Bottom dock: Peaks
        self._peak_table = PeakTableWidget(self)
        self._dock_peaks = QDockWidget("Peaks", self)
        self._dock_peaks.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock_peaks.setFeatures(dock_features)
        self._dock_peaks.setWidget(self._peak_table)
        self._dock_peaks.setMinimumHeight(200)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._dock_peaks)

        # Right dock: Metadata
        self._metadata_panel = MetadataPanel(self)
        self._dock_metadata = QDockWidget("Metadata", self)
        self._dock_metadata.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock_metadata.setFeatures(dock_features)
        self._dock_metadata.setWidget(self._metadata_panel)
        self._dock_metadata.setMinimumWidth(260)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock_metadata)

        # Bottom-right dock: Match Results
        from ui.match_results_panel import MatchResultsPanel  # noqa: PLC0415

        self._match_results_panel = MatchResultsPanel(self)
        self._dock_match = QDockWidget("Match Results", self)
        self._dock_match.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock_match.setFeatures(dock_features)
        self._dock_match.setWidget(self._match_results_panel)
        self._dock_match.setMinimumHeight(150)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock_match)
        self.tabifyDockWidget(self._dock_metadata, self._dock_match)

        # Bottom-right dock: Functional Group Ranking
        self._functional_group_panel = FunctionalGroupPanel(self)
        self._dock_functional_groups = QDockWidget("Functional Groups", self)
        self._dock_functional_groups.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock_functional_groups.setFeatures(dock_features)
        self._dock_functional_groups.setWidget(self._functional_group_panel)
        self._dock_functional_groups.setMinimumWidth(320)
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea,
            self._dock_functional_groups,
        )
        self.tabifyDockWidget(self._dock_metadata, self._dock_functional_groups)

        # Right dock: Consensus interpretation
        self._consensus_panel = ConsensusPanel(self)
        self._dock_consensus = QDockWidget("Consensus", self)
        self._dock_consensus.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock_consensus.setFeatures(dock_features)
        self._dock_consensus.setWidget(self._consensus_panel)
        self._dock_consensus.setMinimumWidth(320)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock_consensus)
        self.tabifyDockWidget(self._dock_metadata, self._dock_consensus)

        # Right dock: Molecule Structure
        self._molecule_widget = MoleculeWidget(self)
        self._dock_structure = QDockWidget("Structure", self)
        self._dock_structure.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self._dock_structure.setFeatures(dock_features)
        self._dock_structure.setWidget(self._molecule_widget)
        self._dock_structure.setMinimumWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock_structure)
        self.tabifyDockWidget(self._dock_metadata, self._dock_structure)

        # Populate View menu with toggle actions for every dock
        for dock in (
            self._dock_vibration,
            self._dock_peaks,
            self._dock_metadata,
            self._dock_match,
            self._dock_functional_groups,
            self._dock_consensus,
            self._dock_structure,
        ):
            self._view_menu.addAction(dock.toggleViewAction())

        self._reload_vibration_presets()
        self._load_functional_group_tags()

    def _load_functional_group_tags(self) -> None:
        """Provide functional-group tag filters to the vibration panel.

        Built from the knowledge base's suggested preset mappings, so picking
        e.g. "Carboxylic Acid" narrows the vibration list to acid-diagnostic
        bands. Failure is non-fatal — the panel just shows no tag filter.
        """
        try:
            from storage.functional_group_repository import (  # noqa: PLC0415
                FunctionalGroupRepository,
            )

            knowledge_base = FunctionalGroupRepository().load()
        except Exception:  # noqa: BLE001
            return
        tags: list[tuple[str, frozenset[str]]] = []
        for group in sorted(knowledge_base.groups, key=lambda g: g.name.lower()):
            names: set[str] = set()
            for band in group.bands:
                names.update(band.suggested_preset_names)
            if names:
                tags.append((group.name, frozenset(names)))
        self._vibration_panel.set_functional_group_tags(tags)

    def _reload_vibration_presets(self) -> None:
        """Fetch vibration presets from the DB and populate the side panel."""
        if not hasattr(self._db, "get_vibration_presets"):
            return
        from core.vibration_presets import VibrationPreset  # noqa: PLC0415

        raw_presets = self._db.get_vibration_presets()
        presets = [
            VibrationPreset(
                name=row["name"],
                typical_range_min=row["typical_range_min"],
                typical_range_max=row["typical_range_max"],
                category=row.get("category", ""),
                description=row.get("description", ""),
                color=row.get("color", "#4A90D9"),
                db_id=row.get("id"),
                is_builtin=bool(row.get("is_builtin", 1)),
            )
            for row in raw_presets
        ]
        self._vibration_presets_cache = presets
        self._vibration_panel.set_presets(presets)
        self._refresh_functional_group_assignment_preview()

    def _setup_statusbar(self) -> None:
        """Set up status bar with cursor position label."""
        self._status_cursor = QLabel("Ready")
        self.statusBar().addPermanentWidget(self._status_cursor)

        self._spectrum_widget.cursor_moved.connect(
            lambda wn, _: self._status_cursor.setText(f"{wn:.2f} cm\u207b\u00b9")
        )

        self._undo_stack.indexChanged.connect(self._on_undo_redo)
        self._undo_stack.cleanChanged.connect(lambda _clean: self._update_window_title())

    def _on_undo_redo(self) -> None:
        """Refresh UI state after undo/redo operations."""
        if self._project is None or self._project.spectrum is None:
            return
        self._project_revision += 1
        preferred_peak = self._peak_table.selected_peak()
        preferred_group_id = self._current_functional_group_id()
        spectrum = (
            self._project.corrected_spectrum
            if self._project.corrected_spectrum is not None
            else self._project.spectrum
        )
        # Keep the user's current zoom/pan — adding a peak while zoomed in must
        # not snap the graph back to the full view.
        self._spectrum_widget.set_spectrum(spectrum, preserve_view=True)
        current_smiles = getattr(self._molecule_widget, "_current_smiles", "")
        current_mol_block = getattr(self._molecule_widget, "_current_mol_block", "")
        if current_smiles != self._project.smiles or current_mol_block != getattr(
            self._project, "mol_block", ""
        ):
            self._molecule_widget.set_structure(
                self._project.smiles,
                mol_block=getattr(self._project, "mol_block", ""),
                image_bytes=self._project.structure_image,
            )
        self._refresh_peak_views(preferred_peak)
        self._refresh_functional_group_analysis(preferred_group_id=preferred_group_id)
        self._update_window_title()

    def _has_unsaved_changes(self) -> bool:
        """Return whether replacing/closing the current project would lose work."""
        if self._project is None:
            return False
        try:
            undo_is_clean = self._undo_stack.isClean()
        except RuntimeError:
            # Qt may destroy child objects before their final signals are delivered
            # while a test/application is tearing the window down.
            undo_is_clean = True
        return self._non_undo_dirty or not undo_is_clean

    def _update_window_title(self) -> None:
        """Show the current project and a conventional unsaved-change marker."""
        title = "IR Spectra Analyzer"
        if self._project is not None:
            project_name = (
                Path(self._current_project_path).name
                if self._current_project_path
                else (self._project.name or "Untitled")
            )
            title = f"{project_name} - {title}"
        if self._has_unsaved_changes():
            title = f"*{title}"
        try:
            self.setWindowTitle(title)
        except RuntimeError:
            # The QUndoStack can emit cleanChanged during QObject destruction.
            return

    def _mark_non_undo_dirty(self) -> None:
        self._non_undo_dirty = True
        self._project_revision += 1
        self._update_window_title()

    def _mark_project_saved(self) -> None:
        self._non_undo_dirty = False
        self._undo_stack.setClean()
        self._update_window_title()

    def _confirm_project_replacement(self) -> bool:
        """Ask how to handle unsaved work before open/replace/close operations."""
        if not self._has_unsaved_changes():
            return True
        answer = QMessageBox.warning(
            self,
            "Unsaved Changes",
            "The current project has unsaved changes. Save them before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self._on_save_project()
        return bool(answer == QMessageBox.StandardButton.Discard)

    def _connect_signals(self) -> None:
        """Wire up inter-component signals."""
        self._spectrum_widget.peak_clicked.connect(self._on_peak_clicked)
        self._spectrum_widget.peak_selected_in_viewer.connect(self._on_peak_selected_in_viewer)
        self._spectrum_widget.peak_delete_requested.connect(self._on_delete_peak_object)
        self._spectrum_widget.peak_label_moved.connect(self._on_peak_label_moved)
        self._peak_table.peak_selected.connect(self._on_peak_selected)
        self._metadata_panel.metadata_changed.connect(self._on_metadata_changed)
        self._vibration_panel.preset_selected.connect(self._on_preset_selected)
        self._vibration_panel.preset_clicked_for_assign.connect(self._on_preset_clicked_for_assign)
        self._vibration_panel.preset_range_requested.connect(self._on_preset_range_requested)
        self._vibration_panel.range_visibility_changed.connect(
            self._on_vibration_range_visibility_changed
        )
        self._vibration_panel.preset_added.connect(self._on_vibration_preset_changed)
        self._vibration_panel.preset_deleted.connect(self._on_vibration_preset_changed)
        self._vibration_panel.preset_remove_requested.connect(self._on_remove_vibration)
        self._peak_table.vibration_edit_requested.connect(self._on_edit_peak_vibration_requested)
        self._match_results_panel.candidate_selected.connect(self._on_match_candidate_selected)
        self._match_results_panel.import_reference.connect(self._on_import_reference)
        self._match_results_panel.match_requested.connect(self._on_match_spectrum)
        self._match_results_panel.apply_assignments_requested.connect(
            self._on_apply_assignments_from_match
        )
        self._match_results_panel.set_structure_preview_provider(
            self._structure_preview.preview_png
        )
        self._functional_group_panel.group_selected.connect(self._on_functional_group_selected)
        self._functional_group_panel.diagnostic_visibility_changed.connect(
            self._on_functional_group_region_visibility_changed
        )
        self._functional_group_panel.suggestion_selected.connect(
            self._on_functional_group_suggestion_selected
        )
        self._consensus_panel.hypothesis_selected.connect(self._on_consensus_hypothesis_selected)
        self._consensus_panel.match_requested.connect(self._on_consensus_match_requested)
        self._molecule_widget.smiles_changed.connect(self._on_structure_edited)
        self._molecule_widget.mol_block_changed.connect(self._on_mol_block_changed)

    @staticmethod
    def _metadata_is_meaningful(metadata) -> bool:
        if metadata is None:
            return False
        return any(
            (
                metadata.title,
                metadata.file_name,
                metadata.operator,
                metadata.instrument,
                metadata.acquired_at,
                metadata.resolution is not None,
                metadata.scans is not None,
                metadata.comments,
                metadata.extra,
            )
        )

    @staticmethod
    def _build_metadata_from_spectrum(spectrum, *, file_name: str = ""):
        from pathlib import Path  # noqa: PLC0415

        from app.config import DEFAULT_INSTRUMENT  # noqa: PLC0415
        from core.metadata import SpectrumMetadata  # noqa: PLC0415

        resolved_file = file_name
        if not resolved_file and spectrum.source_path:
            resolved_file = Path(spectrum.source_path).stem

        return SpectrumMetadata(
            title=spectrum.title,
            file_name=resolved_file,
            operator="",
            instrument=DEFAULT_INSTRUMENT,
            acquired_at=spectrum.acquired_at,
            resolution=spectrum.extra_metadata.get("resolution_cm"),
            scans=spectrum.extra_metadata.get("scans"),
            comments=spectrum.extra_metadata.get("omnic_comment", spectrum.comments),
            extra={
                "omnic_client": spectrum.extra_metadata.get("omnic_custom_info_2", ""),
                "omnic_order": spectrum.extra_metadata.get("omnic_custom_info_1", ""),
            },
        )

    def _resolved_project_metadata(self, project, *, file_name: str = ""):
        if self._metadata_is_meaningful(getattr(project, "metadata", None)):
            return project.metadata
        if project.spectrum is None:
            from core.metadata import SpectrumMetadata  # noqa: PLC0415

            return SpectrumMetadata(file_name=file_name)
        return self._build_metadata_from_spectrum(project.spectrum, file_name=file_name)

    def _apply_project_to_ui(self, project, *, recent_path: str | None = None) -> None:
        from pathlib import Path  # noqa: PLC0415

        self._project = project
        # Loading a fresh spectrum/project resets the tracked save path; the
        # project-load path re-sets it afterwards.
        self._current_project_path = None
        self._undo_stack.clear()
        self._undo_stack.setClean()
        self._non_undo_dirty = False
        self._project_revision = 0
        if recent_path:
            self._add_to_recent(recent_path)

        self._spectrum_widget.set_overlay_spectra([])
        self._clear_match_results()
        display_spectrum = project.corrected_spectrum or project.spectrum
        if display_spectrum is not None:
            self._spectrum_widget.set_spectrum(display_spectrum)

        self._reload_vibration_presets()
        self._refresh_peak_views()

        file_name = ""
        if project.spectrum is not None:
            if project.spectrum.source_path is not None:
                file_name = Path(project.spectrum.source_path).stem
            elif recent_path and not recent_path.lower().endswith(".irproj"):
                file_name = Path(recent_path).stem

        project.metadata = self._resolved_project_metadata(project, file_name=file_name)
        self._metadata_panel.set_metadata(project.metadata)

        self._molecule_widget.set_structure(
            project.smiles,
            mol_block=getattr(project, "mol_block", ""),
            image_bytes=project.structure_image,
        )
        self._refresh_functional_group_analysis()
        self._update_window_title()

    def _sync_project_metadata_from_panel(self) -> None:
        if self._project is None:
            return
        self._on_metadata_changed(self._metadata_panel.current_metadata())

    def _open_recent_path(self, path: str) -> None:
        try:
            if path.lower().endswith(".irproj"):
                self._load_project_from_path(path)
                return
            self._load_spectrum(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Open Error", f"Failed to open recent file:\n{exc}")

    def _load_project_from_path(self, path: str) -> None:
        from pathlib import Path  # noqa: PLC0415

        from storage.project_serializer import ProjectSerializer  # noqa: PLC0415

        if not self._confirm_project_replacement():
            return
        project = ProjectSerializer().load(path)
        self._apply_project_to_ui(project, recent_path=path)
        self._current_project_path = path
        self._mark_project_saved()
        self.statusBar().showMessage(f"Project loaded: {Path(path).name}")

    def _on_metadata_changed(self, metadata) -> None:
        if self._project is None:
            return

        changed = self._project.metadata != metadata
        self._project.metadata = metadata
        self._project.updated_at = datetime.now()

        if self._project.spectrum is not None:
            self._project.spectrum.title = metadata.title
            self._project.spectrum.comments = metadata.comments
        if self._project.corrected_spectrum is not None:
            self._project.corrected_spectrum.title = metadata.title
            self._project.corrected_spectrum.comments = metadata.comments
        if changed:
            self._mark_non_undo_dirty()

    # --- Event handlers ---

    def _on_open_file(self) -> None:
        """Handle File → Open SPA action."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open IR Spectrum",
            "",
            "OMNIC SPA Files (*.spa *.SPA);;All Files (*)",
        )
        if path:
            self._load_spectrum(path)

    def _default_export_basename(self) -> str:
        """Return the filename stem to pre-fill in save/export dialogs.

        Prefers the editable "File" metadata so exported files keep the
        measurement's file identifier; falls back to the project name.
        """
        basename = ""
        metadata = getattr(self._project, "metadata", None)
        if metadata is not None:
            basename = (metadata.file_name or "").strip()
        if not basename and self._project is not None:
            basename = (self._project.name or "").strip()
        # Strip characters that are illegal in filenames on Windows/macOS.
        invalid = '<>:"/\\|?*'
        cleaned = "".join("_" if ch in invalid else ch for ch in basename).strip()
        return cleaned or "spectrum"

    def _last_save_dir(self) -> Path:
        """Return the last folder a project/export was saved into (persisted)."""
        stored = self._settings.get("last_save_dir")
        if stored:
            candidate = Path(stored)
            if candidate.is_dir():
                return candidate
        return Path.home()

    def _remember_save_dir(self, path: str) -> None:
        """Persist the folder of a just-saved file for the next save/export dialog."""
        try:
            self._settings.set("last_save_dir", str(Path(path).parent))
        except Exception:  # noqa: BLE001 — remembering the folder is best-effort
            pass

    def _suggested_save_path(self, extension: str) -> str:
        """Build a default path for a save/export dialog based on the Sample name.

        Prefers the directory of the currently open project; otherwise falls
        back to the last folder anything was saved into, so the next save lands
        in the same place the user chose last time.
        """
        basename = self._default_export_basename()
        if self._current_project_path:
            directory = Path(self._current_project_path).parent
        else:
            directory = self._last_save_dir()
        return str(directory / f"{basename}{extension}")

    def _on_save_project(self) -> bool:
        """Handle File → Save Project action."""
        if self._project is None:
            self.statusBar().showMessage("No project loaded")
            return False

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save IR Project",
            self._current_project_path or self._suggested_save_path(".irproj"),
            "IR Project Files (*.irproj);;JSON files (*.json)",
        )
        if not path:
            return False

        from pathlib import Path  # noqa: PLC0415

        from storage.project_serializer import ProjectSerializer  # noqa: PLC0415

        try:
            self._sync_project_metadata_from_panel()
            ProjectSerializer().save(self._project, path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Save Error", f"Failed to save project:\n{e}")
            return False

        self._current_project_path = path
        self._mark_project_saved()
        self._remember_save_dir(path)
        self.statusBar().showMessage(f"Project saved: {Path(path).name}")
        try:
            self._add_to_recent(path)
            # A project saved into the annotated folder becomes applicable to
            # future matches straight away.
            self._refresh_saved_project_names()
            self._register_saved_project_as_reference(path)
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(
                f"Project saved: {Path(path).name} (follow-up update failed: {e})"
            )
        return True

    def _on_open_project(self) -> None:
        """Handle File → Open Project action."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open IR Project",
            "",
            "IR Project Files (*.irproj);;JSON files (*.json);;All Files (*)",
        )
        if not path:
            return

        try:
            self._load_project_from_path(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Open Error", f"Failed to open project:\n{e}")

    def _load_spectrum(self, path: str) -> None:
        """Load a spectrum file and update the UI."""
        from pathlib import Path  # noqa: PLC0415

        from core.peak import Peak  # noqa: PLC0415
        from core.project import Project  # noqa: PLC0415
        from file_io.format_registry import FormatRegistry  # noqa: PLC0415

        if not self._confirm_project_replacement():
            return
        try:
            registry = FormatRegistry()
            spectrum = registry.read(Path(path))
            loaded_peaks = [
                Peak(position=peak["position"], intensity=peak["intensity"])
                for peak in spectrum.extra_metadata.get("annotated_peaks", [])
            ]
            loaded_peaks.sort(key=lambda peak: peak.position, reverse=True)
            self._project = Project(name=Path(path).stem, spectrum=spectrum, peaks=loaded_peaks)
            self._project.metadata = self._build_metadata_from_spectrum(
                spectrum,
                file_name=Path(path).stem,
            )
            self._apply_project_to_ui(self._project, recent_path=path)

            base = f"Loaded: {Path(path).name} ({spectrum.n_points} points)"
            if self._project.peaks:
                peak_note = f"stored peaks found: {len(self._project.peaks)}"
            elif "annotated_peaks" in spectrum.extra_metadata:
                peak_note = "PEAKTABLE empty"
            else:
                peak_note = "no PEAKTABLE in source file"
            self.statusBar().showMessage(f"{base}, {peak_note}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to load spectrum:\n{e}")

    def _on_tool_mode_changed(self, mode: str) -> None:
        """Switch tool mode in SpectrumWidget."""
        self._spectrum_widget.set_tool_mode(mode)

    def _on_peak_clicked(self, wavenumber: float, intensity: float, click_y: float) -> None:
        """Add a manually clicked peak to the project."""
        if self._project is None:
            return
        from core.commands import AddPeakCommand  # noqa: PLC0415
        from core.peak import Peak  # noqa: PLC0415

        peak = Peak(
            position=wavenumber,
            intensity=intensity,
            manual_placement=True,
            label_offset_x=0.0,
            label_offset_y=click_y - intensity,
        )
        cmd = AddPeakCommand(self._project, peak)
        self._undo_stack.push(cmd)
        self._refresh_peak_views(peak)

    def _on_detect_peaks(self) -> None:
        """Run automatic peak detection on the loaded spectrum."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage("No spectrum loaded")
            return
        from processing.peak_detection import default_prominence, detect_peaks  # noqa: PLC0415

        spectrum = self._project.corrected_spectrum or self._project.spectrum
        invert = spectrum.is_dip_spectrum
        prominence = default_prominence(spectrum)
        peaks = detect_peaks(
            spectrum.wavenumbers, spectrum.intensities, invert=invert, prominence=prominence
        )
        # Wrap all additions in a macro so it's a single Ctrl+Z
        self._undo_stack.beginMacro("Detect peaks")
        from core.commands import AddPeakCommand, DeletePeakCommand  # noqa: PLC0415

        for existing in list(self._project.peaks):
            self._undo_stack.push(DeletePeakCommand(self._project, existing))
        for peak in peaks:
            self._undo_stack.push(AddPeakCommand(self._project, peak))
        self._undo_stack.endMacro()
        self._refresh_peak_views()
        self.statusBar().showMessage(f"Detected {len(self._project.peaks)} peaks")

    def _on_correct_baseline(self) -> None:
        """Apply baseline correction and make it undoable."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage("No spectrum loaded")
            return

        from core.commands import CorrectBaselineCommand  # noqa: PLC0415
        from core.spectrum import SpectralUnit, Spectrum  # noqa: PLC0415
        from processing.baseline import rubber_band_baseline  # noqa: PLC0415

        source_spectrum = self._project.spectrum
        use_upper_hull = source_spectrum.is_dip_spectrum
        corrected_intensities = rubber_band_baseline(
            source_spectrum.wavenumbers,
            source_spectrum.intensities,
            upper=use_upper_hull,
        )

        corrected_spectrum = Spectrum(
            wavenumbers=source_spectrum.wavenumbers.copy(),
            intensities=corrected_intensities,
            title=source_spectrum.title,
            source_path=source_spectrum.source_path,
            acquired_at=source_spectrum.acquired_at,
            y_unit=SpectralUnit.BASELINE_CORRECTED,
            x_unit=source_spectrum.x_unit,
            comments=source_spectrum.comments,
            extra_metadata=dict(source_spectrum.extra_metadata),
        )

        command = CorrectBaselineCommand(self._project, corrected_spectrum)
        self._undo_stack.push(command)

        self.statusBar().showMessage("Baseline corrected (Ctrl+Z to undo)")

    def _on_export(self) -> None:
        """Show export dialog and export in selected format."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage("No spectrum loaded")
            return
        self._sync_project_metadata_from_panel()

        from ui.dialogs.export_dialog import ExportDialog  # noqa: PLC0415

        dialog = ExportDialog(self, preset_manager=self._report_preset_manager)
        if dialog.exec() != ExportDialog.Accepted:
            return

        format_choice = dialog.selected_format

        if format_choice == "pdf":
            if self._export_pdf(dialog.report_options):
                dialog.remember_selected_preset()
        elif format_choice == "csv":
            self._export_csv(include_unassigned=dialog.include_unassigned)
        elif format_choice == "xlsx":
            self._export_xlsx(include_unassigned=dialog.include_unassigned)

    def _export_pdf(self, report_options=None) -> bool:
        """Export the current project to a PDF report."""
        project = self._project
        if project is None or project.spectrum is None:
            self.statusBar().showMessage("No spectrum loaded")
            return False
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export PDF Report",
            self._suggested_save_path(".pdf"),
            "PDF Files (*.pdf)",
        )
        if not path:
            return False

        from pathlib import Path  # noqa: PLC0415

        from reporting.pdf_generator import ReportOptions  # noqa: PLC0415
        from reporting.report_builder import ReportBuilder  # noqa: PLC0415

        if report_options is None:
            report_options = ReportOptions()
        report_options.view_x_range = self._spectrum_widget.get_x_view_range()
        report_options.view_y_range = self._spectrum_widget.get_y_view_range()
        report_options.diagnostic_regions = ()
        report_options.peak_label_placements = {
            id(peak): (label_x, label_y)
            for peak, label_x, label_y in self._spectrum_widget.get_peak_label_placements()
        }

        try:
            builder = ReportBuilder()
            builder.build_with_options(project, Path(path), report_options)
            self._remember_save_dir(path)
            self.statusBar().showMessage(f"PDF exported: {Path(path).name}")
            return True
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Export Error", f"Failed to export PDF:\n{e}")
            return False

    def _export_csv(self, *, include_unassigned: bool = False) -> None:
        """Export peaks to a CSV file."""
        project = self._project
        if project is None or project.spectrum is None:
            self.statusBar().showMessage("No spectrum loaded")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            self._suggested_save_path(".csv"),
            "CSV Files (*.csv);;Text Files (*.txt)",
        )
        if not path:
            return

        from pathlib import Path  # noqa: PLC0415

        from file_io.csv_exporter import CSVExporter  # noqa: PLC0415

        try:
            spectrum = project.corrected_spectrum or project.spectrum
            CSVExporter().export(
                project.peaks,
                Path(path),
                spectrum,
                include_unassigned=include_unassigned,
                project=project,
            )
            self._remember_save_dir(path)
            self.statusBar().showMessage(f"CSV exported: {Path(path).name}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Export Error", f"Failed to export CSV:\n{e}")

    def _export_xlsx(self, *, include_unassigned: bool = False) -> None:
        """Export peaks and spectrum to an Excel file."""
        project = self._project
        if project is None or project.spectrum is None:
            self.statusBar().showMessage("No spectrum loaded")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Excel",
            self._suggested_save_path(".xlsx"),
            "Excel Files (*.xlsx)",
        )
        if not path:
            return

        from pathlib import Path  # noqa: PLC0415

        from file_io.xlsx_exporter import XLSXExporter  # noqa: PLC0415

        try:
            spectrum = project.corrected_spectrum or project.spectrum
            XLSXExporter().export(
                project.peaks,
                Path(path),
                spectrum,
                include_unassigned=include_unassigned,
                project=project,
            )
            self._remember_save_dir(path)
            self.statusBar().showMessage(f"Excel exported: {Path(path).name}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Export Error", f"Failed to export Excel:\n{e}")

    def _on_peak_selected(self, peak) -> None:
        """Update status bar and highlight matching presets when a peak is selected."""
        self.statusBar().showMessage(
            f"Peak: {peak.position:.2f} cm\u207b\u00b9  |  {peak.intensity:.4f}"
        )
        self._spectrum_widget.set_selected_peak(peak)
        self._vibration_panel.highlight_for_peak(peak.position)
        self._vibration_panel.set_active_peak(peak)
        self._set_functional_group_active_peak(peak)

    def _on_remove_vibration(self, preset) -> None:
        """Remove a vibration assignment from the currently selected peak."""
        if self._project is None:
            return
        peak = self._peak_table.selected_peak()
        if peak is None:
            return
        from core.commands import RemovePresetCommand  # noqa: PLC0415

        self._undo_stack.push(RemovePresetCommand(peak, preset))
        self._refresh_peak_views(peak)
        self.statusBar().showMessage(
            f'Removed "{preset.name}" from peak at {peak.position:.1f} cm\u207b\u00b9'
        )

    def _on_edit_peak_vibration_requested(self, peak) -> None:
        """Open a dedicated dialog for manual vibration text editing."""
        if self._project is None:
            return

        existing_text = " / ".join(peak.vibration_labels)
        dialog = VibrationTextEditDialog(
            self,
            title="Edit Peak Vibration",
            label="Vibration:",
            text=existing_text,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_text = dialog.value().strip()
        new_labels = self._parse_vibration_text(new_text)
        new_ids = self._preserve_vibration_ids(peak, new_labels)
        if new_labels == peak.vibration_labels and new_ids == peak.vibration_ids:
            return

        from core.commands import SetPeakVibrationsCommand  # noqa: PLC0415

        self._undo_stack.push(SetPeakVibrationsCommand(peak, new_labels, new_ids))
        self._refresh_peak_views(peak)

        if new_labels:
            self.statusBar().showMessage(
                f"Updated vibration text for {peak.position:.1f} cm\u207b\u00b9"
            )
        else:
            self.statusBar().showMessage(
                f"Cleared vibration text for {peak.position:.1f} cm\u207b\u00b9"
            )

    @staticmethod
    def _preserve_vibration_ids(peak, new_labels: list[str]) -> list[int | None]:
        remaining = list(zip(peak.vibration_labels, peak.vibration_ids, strict=False))
        preserved_ids: list[int | None] = []

        for label in new_labels:
            match_index = next(
                (idx for idx, (old_label, _db_id) in enumerate(remaining) if old_label == label),
                None,
            )
            if match_index is None:
                preserved_ids.append(None)
                continue
            _matched_label, matched_id = remaining.pop(match_index)
            preserved_ids.append(matched_id)

        return preserved_ids

    @staticmethod
    def _parse_vibration_text(text: str) -> list[str]:
        if not text:
            return []
        return [label.strip() for label in text.split(" / ") if label.strip()]

    def _on_preset_range_requested(self, preset) -> None:
        """Outline where the clicked vibration can appear.

        Works for custom entries too — they carry the same typical range as the
        built-in presets. A preset without a usable range simply clears the
        outline rather than drawing a degenerate one.
        """
        range_min = getattr(preset, "typical_range_min", None)
        range_max = getattr(preset, "typical_range_max", None)
        if range_min is None or range_max is None:
            self._spectrum_widget.clear_vibration_range()
            return
        low, high = sorted((float(range_min), float(range_max)))
        if not (math.isfinite(low) and math.isfinite(high)) or high - low <= 0.0:
            self._spectrum_widget.clear_vibration_range()
            return
        self._spectrum_widget.set_vibration_range(low, high)
        self.statusBar().showMessage(
            f"{preset.name}: {low:.0f}–{high:.0f} cm⁻¹",
        )

    def _on_vibration_range_visibility_changed(self, visible: bool) -> None:
        """Show or hide the vibration range outline in the spectrum view."""
        self._spectrum_widget.set_vibration_range_visible(visible)

    def _on_preset_clicked_for_assign(self, preset) -> None:
        """Assign the clicked preset to the currently selected peak.

        Clicking a peak in the viewer only selects it — assignment happens
        exclusively here, when the user clicks a vibration in the panel.
        """
        if self._project is None:
            return
        peak = self._peak_table.selected_peak()
        if peak is None:
            self.statusBar().showMessage("Select a peak first, then click a vibration to assign.")
            return
        from core.commands import AssignPresetCommand  # noqa: PLC0415

        self._undo_stack.push(AssignPresetCommand(peak, preset))
        self._refresh_peak_views(peak)
        self.statusBar().showMessage(
            f'Assigned "{preset.name}" to peak at {peak.position:.1f} cm\u207b\u00b9'
        )

    def _on_peak_selected_in_viewer(self, peak) -> None:
        """Select peak in table and highlight presets when user clicks a peak in the chart."""
        self._spectrum_widget.set_selected_peak(peak)
        self._peak_table.select_peak(peak)
        self._vibration_panel.highlight_for_peak(peak.position)
        self._vibration_panel.set_active_peak(peak)
        self._set_functional_group_active_peak(peak)
        self.statusBar().showMessage(
            f"Peak: {peak.position:.2f} cm\u207b\u00b9  |  {peak.intensity:.4f}"
        )

    def _on_clear_peaks(self) -> None:
        """Remove all peaks from the project (undoable as a single macro)."""
        if self._project is None or not self._project.peaks:
            return
        from core.commands import DeletePeakCommand  # noqa: PLC0415

        self._undo_stack.beginMacro("Clear peaks")
        for peak in list(self._project.peaks):
            self._undo_stack.push(DeletePeakCommand(self._project, peak))
        self._undo_stack.endMacro()
        self._refresh_peak_views()
        self.statusBar().showMessage("Peaks cleared")

    def _on_arrange_peak_labels(self) -> None:
        """Auto-arrange peak labels without disturbing existing workflow until requested."""
        if self._project is None or not self._project.peaks:
            self.statusBar().showMessage("No peaks available to arrange")
            return

        placements = self._spectrum_widget.compute_auto_label_placements()
        if not placements:
            self.statusBar().showMessage("No peak labels available to arrange")
            return

        if all(
            abs(peak.label_offset_x - offset_x) <= 1e-6
            and abs(peak.label_offset_y - offset_y) <= 1e-6
            and peak.manual_placement
            for peak, offset_x, offset_y in placements
        ):
            self.statusBar().showMessage("Peak labels are already arranged")
            return

        from core.commands import SetPeakLabelPlacementsCommand  # noqa: PLC0415

        preferred_peak = self._peak_table.selected_peak()
        self._undo_stack.push(SetPeakLabelPlacementsCommand(placements))
        self._refresh_peak_views(preferred_peak)
        self._spectrum_widget.reset_view()
        self.statusBar().showMessage("Peak labels arranged")

    def _on_preset_selected(self, preset) -> None:
        """Assign the selected vibration preset to the currently active peak."""
        if self._project is None:
            return
        peak = self._peak_table.selected_peak()
        if peak is None:
            self.statusBar().showMessage("Select a peak first, then double-click a preset.")
            return
        from core.commands import AssignPresetCommand  # noqa: PLC0415

        self._undo_stack.push(AssignPresetCommand(peak, preset))
        self._refresh_peak_views(peak)
        self.statusBar().showMessage(
            f'Assigned "{preset.name}" to peak at {peak.position:.1f} cm\u207b\u00b9'
        )

    def _on_vibration_preset_changed(self) -> None:
        """Reload vibration presets after a custom preset is added or deleted."""
        self._reload_vibration_presets()

    def _on_structure_edited(self, smiles: str) -> None:
        """Handle SMILES change emitted by MoleculeWidget after dialog acceptance."""
        if self._project is None:
            return
        from core.commands import SetProjectSMILESCommand  # noqa: PLC0415

        mol_block = getattr(self._molecule_widget, "_current_mol_block", "") or ""
        self._undo_stack.push(SetProjectSMILESCommand(self._project, smiles, mol_block))
        self.statusBar().showMessage("Proposed structure updated")

    def _on_mol_block_changed(self, mol_block: str) -> None:
        """No-op — mol_block is captured atomically by SetProjectSMILESCommand.

        Kept so the widget's `mol_block_changed` signal still has a registered slot
        and so future non-undoable callers remain supported without breaking the
        connection.
        """
        return

    def _on_delete_peak(self) -> None:
        """Delete the currently selected peak."""
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return
        if self._project is None:
            return
        peak = self._peak_table.selected_peak()
        if peak is None:
            return
        from core.commands import DeletePeakCommand  # noqa: PLC0415

        self._undo_stack.push(DeletePeakCommand(self._project, peak))
        self._refresh_peak_views()
        self.statusBar().showMessage(f"Deleted peak at {peak.position:.1f} cm\u207b\u00b9")

    def _on_delete_peak_object(self, peak: Peak) -> None:
        """Delete a specific peak object (emitted from shift+click on label)."""
        if self._project is None:
            return
        from core.commands import DeletePeakCommand  # noqa: PLC0415

        self._undo_stack.push(DeletePeakCommand(self._project, peak))
        self._refresh_peak_views()

    def _on_peak_label_moved(self, peak: object) -> None:
        """Track direct plot-label movement, which is intentionally not undoable."""
        if self._project is None:
            return
        if any(existing is peak for existing in self._project.peaks):
            self._mark_non_undo_dirty()

    def _on_match_spectrum(self) -> None:
        """Run spectral matching against the reference database."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage("No spectrum loaded")
            return

        if self._reference_search_thread is not None:
            self.statusBar().showMessage("Reference search is already running")
            return

        spectrum = self._project.corrected_spectrum or self._project.spectrum
        if self._db.is_in_memory:
            self._execute_match_spectrum_search(spectrum)
            return

        from ui.workers.reference_library_worker import (  # noqa: PLC0415
            ReferenceLibrarySearchWorker,
        )

        worker = ReferenceLibrarySearchWorker(
            db_path=self._db.db_path,
            project_root=self._reference_library_service.project_root,
            selected_library_folder=self._reference_library_service.selected_library_folder(),
            spectrum=spectrum,
            top_n=self._MATCH_RESULTS_LIMIT,
            auto_import_project_library=True,
            name_filter=self._match_results_panel.name_filter(),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        context = self._current_match_context()
        worker.completed.connect(
            lambda outcome, search_context=context: self._on_match_spectrum_completed(
                outcome, search_context
            )
        )
        worker.failed.connect(
            lambda message, search_context=context: self._on_match_spectrum_failed(
                message, search_context
            )
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_reference_search_thread_finished)
        thread.started.connect(
            lambda: QMetaObject.invokeMethod(worker, "run", Qt.ConnectionType.QueuedConnection)
        )
        self._reference_search_thread = thread
        self._reference_search_context = context
        self._set_match_search_busy(True)
        thread.start()

    def _execute_match_spectrum_search(self, spectrum) -> None:
        """Run spectral matching synchronously (used for tests/in-memory DB)."""
        try:
            outcome = self._reference_library_service.search_spectrum(
                spectrum,
                top_n=self._MATCH_RESULTS_LIMIT,
                name_filter=self._match_results_panel.name_filter(),
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Match Error", f"Matching failed:\n{e}")
            return
        self._apply_match_spectrum_outcome(outcome)

    def _current_match_context(self) -> tuple[int, int, str]:
        return (
            id(self._project),
            self._project_revision,
            self._match_results_panel.name_filter(),
        )

    def _on_match_spectrum_completed(
        self,
        outcome,
        search_context: tuple[int, int, str] | None = None,
    ) -> None:
        """Apply background search results once the worker finishes."""
        if search_context is not None and search_context != self._current_match_context():
            self.statusBar().showMessage(
                "Matching result ignored because the project or filter changed."
            )
            return
        self._apply_match_spectrum_outcome(outcome)

    def _on_match_spectrum_failed(
        self,
        message: str,
        search_context: tuple[int, int, str] | None = None,
    ) -> None:
        """Show a background search failure to the user."""
        if search_context is not None and search_context != self._current_match_context():
            return
        self.statusBar().showMessage("Matching failed")
        QMessageBox.critical(self, "Match Error", f"Matching failed:\n{message}")

    def _on_reference_search_thread_finished(self) -> None:
        """Reset UI state after a background reference search completes."""
        self._reference_search_thread = None
        self._reference_search_context = None
        self._set_match_search_busy(False)

    def _apply_match_spectrum_outcome(self, outcome) -> None:
        """Update the match-results UI from a completed search outcome."""
        if not outcome.references:
            if outcome.library_folder is None:
                self.statusBar().showMessage(
                    "Choose a reference library folder first in Database -> Reference Library."
                )
            else:
                self.statusBar().showMessage(
                    "No reference spectra available. Sync or import the selected library first."
                )
            self._clear_match_results()
            return

        self._current_match_results = list(outcome.results)
        self._refresh_saved_project_names()
        self._match_results_panel.set_results(list(outcome.results))
        self._refresh_consensus_analysis()
        if outcome.imported_summary is not None and outcome.imported_summary.imported > 0:
            self.statusBar().showMessage(
                "Imported "
                f"{outcome.imported_summary.imported} bundled references and matched "
                f"against {outcome.reference_count} spectra"
            )
        else:
            self.statusBar().showMessage(f"Matched against {outcome.reference_count} references")

    def _annotated_projects_dir(self) -> Path | None:
        """Return the configured folder of previously analysed .irproj projects."""
        stored = self._settings.get("annotated_projects_folder")
        if stored:
            candidate = Path(stored)
            if candidate.is_dir():
                return candidate
        return None

    def _auto_register_saved_projects(self) -> bool:
        """Whether Save Project also registers the spectrum as a reference."""
        stored = self._settings.get("auto_register_saved_projects")
        return True if stored is None else bool(stored)

    def _on_auto_register_toggled(self, enabled: bool) -> None:
        """Persist the auto-registration preference."""
        self._settings.set("auto_register_saved_projects", bool(enabled))
        self.statusBar().showMessage(
            "Saved projects are added to the reference library"
            if enabled
            else "Saved projects are no longer added to the reference library"
        )

    def _register_saved_project_as_reference(self, project_path: str) -> None:
        """Store a just-saved project's spectrum in the searchable reference library.

        The analyst's own measurements usually live outside the reference-library
        folder, so without this a freshly analysed spectrum never turns up in
        Match Spectrum for the next sample of the same series.
        """
        if not self._auto_register_saved_projects():
            return
        if self._project is None or self._project.spectrum is None:
            return
        registration = self._register_spectrum_as_reference(
            name=Path(project_path).stem,
            source_path=project_path,
        )
        if registration is None:
            return
        if registration.status == "added":
            self.statusBar().showMessage(
                f"Project saved: {Path(project_path).name} — also added to the "
                f'reference library as "{registration.name}"'
            )
        elif registration.status == "updated":
            self.statusBar().showMessage(
                f"Project saved: {Path(project_path).name} — reference "
                f'"{registration.name}" updated'
            )

    def _register_spectrum_as_reference(self, *, name: str, source_path: str):
        """Register the current project's raw spectrum as a reference, or None on error."""
        if self._project is None or self._project.spectrum is None:
            return None
        metadata = getattr(self._project, "metadata", None)
        description = (getattr(metadata, "title", "") or "").strip()
        try:
            # The raw spectrum is stored on purpose: library files are raw too,
            # so a later measurement of the same substance is compared like-to-like.
            return self._reference_library_service.register_project_spectrum(
                name=name,
                spectrum=self._project.spectrum,
                source_path=source_path,
                description=description,
            )
        except Exception as exc:  # noqa: BLE001 — a failed reference must not lose the project
            self.statusBar().showMessage(f"Could not add to reference library: {exc}")
            return None

    def _on_add_current_spectrum_to_library(self) -> None:
        """Database → Add Current Spectrum to Reference Library."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage("No spectrum loaded")
            return
        name = self._default_export_basename()
        source = self._current_project_path or (self._project.spectrum.source_path or name)
        registration = self._register_spectrum_as_reference(name=name, source_path=str(source))
        if registration is None:
            return
        if registration.status == "skipped":
            QMessageBox.information(
                self,
                "Reference Library",
                f'"{registration.name}" was not added — {registration.reason}.',
            )
            return
        verb = "Added" if registration.status == "added" else "Updated"
        self.statusBar().showMessage(f'{verb} reference "{registration.name}"')

    def _saved_project_paths(self) -> dict[str, Path]:
        """Map lowercased project name to its .irproj in the annotated projects folder."""
        folder = self._annotated_projects_dir()
        if folder is None:
            return {}
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            return {}
        return {
            entry.stem.lower(): entry
            for entry in entries
            if entry.is_file() and entry.suffix.lower() == ".irproj"
        }

    def _refresh_saved_project_names(self) -> dict[str, Path]:
        """Tell the match panel and the preview service about the saved projects."""
        saved_projects = self._saved_project_paths()
        self._match_results_panel.set_saved_project_names(saved_projects.keys())
        self._structure_preview.set_project_paths(saved_projects)
        return saved_projects

    def _on_set_annotated_projects_folder(self) -> None:
        """Let the user pick the folder that holds previously analysed .irproj files."""
        start = self._annotated_projects_dir()
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Choose Annotated Projects Folder (.irproj)",
            str(start) if start else "",
        )
        if not chosen:
            return
        self._settings.set("annotated_projects_folder", chosen)
        self._refresh_saved_project_names()
        self.statusBar().showMessage(f"Annotated projects folder: {Path(chosen).name}")

    def _on_apply_assignments_from_match(self, result) -> None:
        """Copy assignments + structure from the matched spectrum's saved .irproj.

        Looks up ``<match name>.irproj`` in the annotated-projects folder, maps
        its assigned peaks onto the current spectrum's nearest peaks (within a
        tolerance window), fills only unassigned peaks, and copies the structure
        only when the current project has none.
        """
        if self._project is None or self._project.spectrum is None:
            return
        folder = self._annotated_projects_dir()
        if folder is None:
            QMessageBox.information(
                self,
                "Annotated Projects Folder",
                "First choose the folder with your analysed .irproj files:\n"
                "Database → Set Annotated Projects Folder…",
            )
            return

        saved_projects = self._refresh_saved_project_names()
        project_path = saved_projects.get(str(result.name).strip().lower())
        if project_path is None:
            QMessageBox.information(
                self,
                "No Saved Project",
                f'No "{result.name}.irproj" found in the annotated projects folder.\n'
                "Assignments can only be copied from a spectrum you have already "
                "analysed and saved there.",
            )
            return

        from processing.assignment_transfer import plan_assignment_transfer  # noqa: PLC0415
        from storage.project_serializer import ProjectSerializer  # noqa: PLC0415

        try:
            reference_project = ProjectSerializer().load(str(project_path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Apply Error", f"Failed to read {project_path.name}:\n{exc}")
            return

        transfers = plan_assignment_transfer(
            self._project.peaks,
            reference_project.peaks,
            tolerance=self._ASSIGNMENT_TRANSFER_TOLERANCE,
        )
        copy_structure = not (
            self._project.smiles or getattr(self._project, "mol_block", "")
        ) and bool(reference_project.smiles or getattr(reference_project, "mol_block", ""))
        if not transfers and not copy_structure:
            self.statusBar().showMessage(
                f"Nothing to copy from {result.name} — peaks already assigned or none matched"
            )
            return

        from core.commands import SetPeakVibrationsCommand, SetProjectSMILESCommand  # noqa: PLC0415

        self._undo_stack.beginMacro(f"Apply assignments from {result.name}")
        for transfer in transfers:
            self._undo_stack.push(
                SetPeakVibrationsCommand(
                    transfer.peak,
                    transfer.vibration_labels,
                    transfer.vibration_ids,
                )
            )
        if copy_structure:
            self._undo_stack.push(
                SetProjectSMILESCommand(
                    self._project,
                    reference_project.smiles,
                    getattr(reference_project, "mol_block", ""),
                )
            )
        self._undo_stack.endMacro()

        n_ref = sum(1 for p in reference_project.peaks if p.vibration_labels)
        struct_note = " and structure" if copy_structure else ""
        self.statusBar().showMessage(
            f"Copied {len(transfers)}/{n_ref} assignments{struct_note} from {result.name}"
        )

    def _set_match_search_busy(self, busy: bool) -> None:
        """Toggle the match action while a background reference search is running."""
        if self._toolbar._match_action is not None:
            self._toolbar._match_action.setEnabled(not busy)
        if busy:
            self.statusBar().showMessage("Matching spectrum against reference library…")

    def _on_match_candidate_selected(self, result) -> None:
        """Show the selected reference spectrum as overlay and its band differences."""
        from core.spectrum import Spectrum  # noqa: PLC0415

        ref = self._reference_library_service.get_reference_spectrum(int(result.ref_id))
        if ref is None:
            return
        overlay = Spectrum(
            wavenumbers=ref["wavenumbers"],
            intensities=ref["intensities"],
            title=ref["name"],
            y_unit=self._spectral_unit_or_default(ref.get("y_unit")),
        )
        self._spectrum_widget.set_overlay_spectra([overlay])
        self._match_results_panel.set_band_difference(self._band_difference_summary(overlay))

    @staticmethod
    def _spectral_unit_or_default(value):
        """Return a SpectralUnit for a stored y-unit string, absorbance if unknown."""
        from core.spectrum import SpectralUnit  # noqa: PLC0415

        try:
            return SpectralUnit(value)
        except ValueError:
            return SpectralUnit.ABSORBANCE

    def _band_difference_summary(self, reference_spectrum) -> str:
        """Describe which bands the current spectrum and a reference do not share."""
        if self._project is None or self._project.spectrum is None:
            return ""
        from processing.band_difference import compare_bands  # noqa: PLC0415

        query = self._project.corrected_spectrum or self._project.spectrum
        try:
            return compare_bands(query, reference_spectrum).summary()
        except Exception:  # noqa: BLE001 — a diagnostic must never block the overlay
            return ""

    def _on_functional_group_selected(self, result) -> None:
        """Highlight diagnostic regions for the selected functional group."""
        self._spectrum_widget.set_diagnostic_regions(list(result.bands))
        self._refresh_functional_group_assignment_preview()

    def _on_functional_group_region_visibility_changed(self, visible: bool) -> None:
        """Show or hide functional-group diagnostic overlays in the spectrum view."""
        self._spectrum_widget.set_diagnostic_regions_visible(visible)

    def _on_functional_group_suggestion_selected(self, band) -> None:
        """Assign a suggested vibration to the selected peak via the existing command path."""
        if self._project is None:
            return
        peak = self._peak_table.selected_peak()
        if peak is None:
            self.statusBar().showMessage("Select a peak first, then double-click a suggestion.")
            return
        if not band.covers_wavenumber(peak.position):
            self.statusBar().showMessage("Selected peak is outside the suggested vibration range.")
            return

        preset = self._find_best_preset_for_band(band, peak.position)
        if preset is None:
            self.statusBar().showMessage("No matching vibration preset found for this suggestion.")
            return

        from core.commands import AssignPresetCommand  # noqa: PLC0415

        preferred_group_id = self._current_functional_group_id()
        self._undo_stack.push(AssignPresetCommand(peak, preset))
        self._refresh_peak_views(peak)
        self._restore_functional_group_selection(preferred_group_id)
        self.statusBar().showMessage(
            f'Assigned suggested vibration "{preset.name}" to {peak.position:.1f} cm\u207b\u00b9'
        )

    def _on_consensus_hypothesis_selected(self, group_id: str) -> None:
        """Navigate from the consensus panel into the functional-group panel."""
        self._functional_group_panel.select_group_by_id(group_id)

    def _on_consensus_match_requested(self, ref_id: int) -> None:
        """Navigate from the consensus panel into the match-results panel."""
        self._match_results_panel.select_result_by_ref_id(ref_id)

    def _clear_match_results(self) -> None:
        """Drop cached matching state for the current project."""
        self._current_match_results = []
        self._match_results_panel.set_results([])
        self._match_results_panel.set_band_difference("")
        self._spectrum_widget.set_overlay_spectra([])
        self._refresh_consensus_analysis()

    def _refresh_consensus_analysis(self) -> None:
        """Rebuild the read-only interpretation summary from current cached results."""
        analysis = build_consensus_analysis(
            self._project,
            self._current_functional_group_results,
            self._current_match_results,
        )
        self._consensus_panel.set_analysis(analysis)

    def _refresh_functional_group_analysis(self, *, preferred_group_id: str | None = None) -> None:
        """Recompute functional-group scores from the current project spectrum."""
        if self._project is None or self._project.spectrum is None:
            self._current_functional_group_results = []
            self._functional_group_panel.clear()
            self._spectrum_widget.set_diagnostic_regions([])
            self._refresh_consensus_analysis()
            return

        from processing.functional_group_scoring import score_functional_groups  # noqa: PLC0415

        try:
            analysis = score_functional_groups(
                self._project.spectrum,
                self._project.corrected_spectrum,
            )
        except Exception as exc:  # noqa: BLE001 — a broken/missing knowledge base
            # must degrade to an empty panel instead of aborting spectrum load
            # (e.g. data file missing from a packaged build).
            self._current_functional_group_results = []
            self._functional_group_panel.clear()
            self._spectrum_widget.set_diagnostic_regions([])
            self._refresh_consensus_analysis()
            self.statusBar().showMessage(f"Functional-group analysis unavailable: {exc}")
            return
        self._current_functional_group_results = list(analysis.results)
        self._functional_group_panel.set_results(list(analysis.results))
        self._restore_functional_group_selection(preferred_group_id)
        self._set_functional_group_active_peak(self._peak_table.selected_peak())
        self._refresh_consensus_analysis()

    def _current_functional_group_id(self) -> str | None:
        """Return the currently selected functional-group ID, if any."""
        result = self._functional_group_panel.current_result()
        if result is None:
            return None
        return str(result.group_id)

    def _restore_functional_group_selection(self, group_id: str | None) -> None:
        """Re-select one functional-group row after a refresh when possible."""
        if group_id:
            self._functional_group_panel.select_group_by_id(group_id)

    def _find_best_preset_for_band(self, band, wavenumber: float):
        candidate_names = set(band.suggested_preset_names)
        if not candidate_names:
            return None

        named_candidates = [
            preset for preset in self._vibration_presets_cache if preset.name in candidate_names
        ]
        if not named_candidates:
            return None

        covering_candidates = [
            preset for preset in named_candidates if preset.covers_wavenumber(wavenumber)
        ]
        if covering_candidates:
            named_candidates = covering_candidates

        return min(
            named_candidates,
            key=lambda preset: abs(
                ((preset.typical_range_min + preset.typical_range_max) / 2.0) - wavenumber
            ),
        )

    def _set_functional_group_active_peak(self, peak) -> None:
        self._functional_group_panel.set_active_peak(peak)
        self._refresh_functional_group_assignment_preview()

    def _refresh_peak_views(self, preferred_peak=None) -> None:
        if self._project is None:
            return

        # Decide the active peak up front so the viewer renders its selected
        # marker in a single pass (avoids a second re-render).
        if preferred_peak is not None and any(
            existing_peak is preferred_peak for existing_peak in self._project.peaks
        ):
            active_peak = preferred_peak
        else:
            candidate = self._peak_table.selected_peak()
            active_peak = (
                candidate
                if candidate is not None
                and any(existing is candidate for existing in self._project.peaks)
                else None
            )
        self._spectrum_widget.set_selected_peak(active_peak, refresh=False)

        self._peak_table.set_peaks(self._project.peaks)
        self._spectrum_widget.set_peaks(self._project.peaks)

        if active_peak is not None:
            self._peak_table.select_peak(active_peak)

        if active_peak is not None:
            self._vibration_panel.highlight_for_peak(active_peak.position)
            self._vibration_panel.set_active_peak(active_peak)
        else:
            self._vibration_panel.clear_peak_context()
        self._set_functional_group_active_peak(active_peak)
        self._refresh_consensus_analysis()

    def _refresh_functional_group_assignment_preview(self) -> None:
        result = self._functional_group_panel.current_result()
        peak = self._peak_table.selected_peak()
        if result is None or peak is None:
            self._functional_group_panel.set_assignment_preview_map({})
            return

        preview_map: dict[str, str] = {}
        for band in result.suggested_bands:
            if not band.covers_wavenumber(peak.position):
                continue
            preset = self._find_best_preset_for_band(band, peak.position)
            if preset is None:
                continue
            preview_map[band.band_id] = preset.name
        self._functional_group_panel.set_assignment_preview_map(preview_map)

    def _on_import_reference(self) -> None:
        """Import a SPA file as a reference spectrum into the database."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Reference Spectrum",
            "",
            "OMNIC SPA Files (*.spa *.SPA);;All Files (*)",
        )
        if not path:
            return

        from pathlib import Path  # noqa: PLC0415

        from app.reference_import import ReferenceImportService  # noqa: PLC0415

        try:
            imported = ReferenceImportService(self._db).import_reference_file(Path(path))
            self.statusBar().showMessage(f"Reference imported: {imported.name}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Import Error", f"Failed to import reference:\n{e}")

    def _rebuild_recent_menu(self) -> None:
        """Rebuild the Open Recent submenu from settings."""
        if self._recent_menu is None:
            return
        self._recent_menu.clear()
        recent: list[str] = self._settings.get("recent_files") or []
        if not recent:
            no_action = self._recent_menu.addAction("(empty)")
            no_action.setEnabled(False)
            return
        for path in recent:
            action = self._recent_menu.addAction(path)
            action.triggered.connect(lambda checked=False, p=path: self._open_recent_path(p))

    def _add_to_recent(self, path: str) -> None:
        """Add path to recent files list (max 5, deduped, newest first)."""
        recent: list[str] = list(self._settings.get("recent_files") or [])
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self._settings.set("recent_files", recent[:5])
        self._rebuild_recent_menu()

    def _on_open_reference_library(self) -> None:
        """Open the Reference Library management dialog."""
        current_spectrum = None
        if self._project is not None:
            current_spectrum = self._project.corrected_spectrum or self._project.spectrum

        from ui.dialogs.reference_library_dialog import ReferenceLibraryDialog  # noqa: PLC0415

        dlg = ReferenceLibraryDialog(
            self._db,
            parent=self,
            library_service=self._reference_library_service,
            current_spectrum=current_spectrum,
        )
        dlg.reference_opened.connect(self._load_spectrum)
        dlg.exec()

    def _on_batch_import_references(self) -> None:
        """Open the batch reference import dialog."""
        from ui.dialogs.batch_import_dialog import BatchImportDialog  # noqa: PLC0415

        dlg = BatchImportDialog(self._db, parent=self)
        dlg.exec()

    def _on_batch_export_pdf(self) -> None:
        """Open the batch PDF export dialog."""
        from ui.dialogs.batch_pdf_export_dialog import BatchPDFExportDialog  # noqa: PLC0415

        dlg = BatchPDFExportDialog(parent=self, preset_manager=self._report_preset_manager)
        dlg.exec()

    def _on_batch_generate_projects(self) -> None:
        """Open the batch project generation dialog."""
        from ui.dialogs.batch_project_generation_dialog import (  # noqa: PLC0415
            BatchProjectGenerationDialog,
        )

        dlg = BatchProjectGenerationDialog(parent=self)
        dlg.exec()

    def _on_batch_export_project_pdfs(self) -> None:
        """Open the batch project PDF export dialog."""
        from ui.dialogs.batch_project_pdf_export_dialog import (  # noqa: PLC0415
            BatchProjectPDFExportDialog,
        )

        dlg = BatchProjectPDFExportDialog(parent=self, preset_manager=self._report_preset_manager)
        dlg.exec()

    def _on_about(self) -> None:
        """Show About dialog."""
        from ui.dialogs.about_dialog import AboutDialog  # noqa: PLC0415

        AboutDialog(self).exec()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Prevent data loss and avoid destroying a running search thread."""
        # A headless/offscreen session has no user who could answer a modal
        # prompt. Interactive hidden windows still go through the data-loss guard.
        if not self.isVisible() and QApplication.platformName().casefold() == "offscreen":
            event.accept()
            return
        if self._reference_search_thread is not None:
            QMessageBox.information(
                self,
                "Operation in Progress",
                "Reference matching is still running. Please wait for it to finish before closing.",
            )
            event.ignore()
            return
        if self._confirm_project_replacement():
            event.accept()
        else:
            event.ignore()
