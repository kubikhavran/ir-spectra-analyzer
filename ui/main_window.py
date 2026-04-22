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

from datetime import datetime

from PySide6.QtCore import QMetaObject, Qt, QThread
from PySide6.QtGui import QKeySequence, QShortcut, QUndoStack
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
)

from app.report_presets import ReportPresetManager
from storage.database import Database
from storage.settings import Settings
from ui.functional_group_panel import FunctionalGroupPanel
from ui.metadata_panel import MetadataPanel
from ui.molecule_widget import MoleculeWidget
from ui.peak_table_widget import PeakTableWidget
from ui.spectrum_widget import SpectrumWidget
from ui.toolbar import MainToolbar
from ui.vibration_panel import VibrationPanel
from ui.vibration_text_edit import VibrationTextEditDialog


class MainWindow(QMainWindow):
    """Main application window with dockable analysis panels."""

    _MATCH_RESULTS_LIMIT = 20

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
        self._project = None
        self._recent_menu: QMenu | None = None
        self._undo_stack = QUndoStack(self)
        self._last_search_refs: list = []  # cached from last _on_match_spectrum call
        self._reference_search_thread: QThread | None = None
        self._vibration_presets_cache: list = []
        self._molecule_widget: MoleculeWidget
        self._report_preset_manager = ReportPresetManager(settings)
        self._pending_preset = None  # preset clicked in VibrationPanel, awaiting peak click
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
        open_action = file_menu.addAction("&Open SPA...")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_file)

        open_project_action = file_menu.addAction("Open &Project...")
        open_project_action.triggered.connect(self._on_open_project)

        save_project_action = file_menu.addAction("&Save Project...")
        save_project_action.setShortcut("Ctrl+S")
        save_project_action.triggered.connect(self._on_save_project)

        self._recent_menu = file_menu.addMenu("Open &Recent")
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
            self._dock_structure,
        ):
            self._view_menu.addAction(dock.toggleViewAction())

        self._reload_vibration_presets()

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

    def _on_undo_redo(self) -> None:
        """Refresh UI state after undo/redo operations."""
        if self._project is None or self._project.spectrum is None:
            return
        preferred_peak = self._peak_table.selected_peak()
        spectrum = (
            self._project.corrected_spectrum
            if self._project.corrected_spectrum is not None
            else self._project.spectrum
        )
        self._spectrum_widget.set_spectrum(spectrum)
        self._refresh_peak_views(preferred_peak)
        self._refresh_functional_group_analysis()

    def _connect_signals(self) -> None:
        """Wire up inter-component signals."""
        self._spectrum_widget.peak_clicked.connect(self._on_peak_clicked)
        self._spectrum_widget.peak_selected_in_viewer.connect(self._on_peak_selected_in_viewer)
        self._spectrum_widget.peak_delete_requested.connect(self._on_delete_peak_object)
        self._peak_table.peak_selected.connect(self._on_peak_selected)
        self._metadata_panel.metadata_changed.connect(self._on_metadata_changed)
        self._vibration_panel.preset_selected.connect(self._on_preset_selected)
        self._vibration_panel.preset_clicked_for_assign.connect(self._on_preset_clicked_for_assign)
        self._vibration_panel.preset_added.connect(self._on_vibration_preset_changed)
        self._vibration_panel.preset_deleted.connect(self._on_vibration_preset_changed)
        self._vibration_panel.preset_remove_requested.connect(self._on_remove_vibration)
        self._peak_table.vibration_label_removed.connect(self._on_vibration_label_removed)
        self._peak_table.vibration_edit_requested.connect(self._on_edit_peak_vibration_requested)
        self._match_results_panel.candidate_selected.connect(self._on_match_candidate_selected)
        self._match_results_panel.import_reference.connect(self._on_import_reference)
        self._functional_group_panel.group_selected.connect(self._on_functional_group_selected)
        self._functional_group_panel.diagnostic_visibility_changed.connect(
            self._on_functional_group_region_visibility_changed
        )
        self._functional_group_panel.suggestion_selected.connect(
            self._on_functional_group_suggestion_selected
        )
        self._molecule_widget.smiles_changed.connect(self._on_structure_edited)
        self._molecule_widget.mol_block_changed.connect(self._on_mol_block_changed)

    @staticmethod
    def _metadata_is_meaningful(metadata) -> bool:
        if metadata is None:
            return False
        return any(
            (
                metadata.title,
                metadata.sample_name,
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
    def _build_metadata_from_spectrum(spectrum, *, sample_name: str = ""):
        from pathlib import Path  # noqa: PLC0415

        from core.metadata import SpectrumMetadata  # noqa: PLC0415

        resolved_sample = sample_name
        if not resolved_sample and spectrum.source_path:
            resolved_sample = Path(spectrum.source_path).stem

        return SpectrumMetadata(
            title=spectrum.title,
            sample_name=resolved_sample,
            operator="",
            instrument=str(spectrum.extra_metadata.get("instrument_serial", "")),
            acquired_at=spectrum.acquired_at,
            resolution=spectrum.extra_metadata.get("resolution_cm"),
            scans=spectrum.extra_metadata.get("scans"),
            comments=spectrum.extra_metadata.get("omnic_comment", spectrum.comments),
            extra={
                "omnic_client": spectrum.extra_metadata.get("omnic_custom_info_2", ""),
                "omnic_order": spectrum.extra_metadata.get("omnic_custom_info_1", ""),
            },
        )

    def _resolved_project_metadata(self, project, *, sample_name: str = ""):
        if self._metadata_is_meaningful(getattr(project, "metadata", None)):
            return project.metadata
        if project.spectrum is None:
            from core.metadata import SpectrumMetadata  # noqa: PLC0415

            return SpectrumMetadata(sample_name=sample_name)
        return self._build_metadata_from_spectrum(project.spectrum, sample_name=sample_name)

    def _apply_project_to_ui(self, project, *, recent_path: str | None = None) -> None:
        from pathlib import Path  # noqa: PLC0415

        self._project = project
        self._undo_stack.clear()
        if recent_path:
            self._add_to_recent(recent_path)

        self._spectrum_widget.set_overlay_spectra([])
        display_spectrum = project.corrected_spectrum or project.spectrum
        if display_spectrum is not None:
            self._spectrum_widget.set_spectrum(display_spectrum)

        self._reload_vibration_presets()
        self._refresh_peak_views()

        sample_name = ""
        if project.spectrum is not None:
            if project.spectrum.source_path is not None:
                sample_name = Path(project.spectrum.source_path).stem
            elif recent_path and not recent_path.lower().endswith(".irproj"):
                sample_name = Path(recent_path).stem

        project.metadata = self._resolved_project_metadata(project, sample_name=sample_name)
        self._metadata_panel.set_metadata(project.metadata)

        self._molecule_widget.set_structure(
            project.smiles,
            mol_block=getattr(project, "mol_block", ""),
            image_bytes=project.structure_image,
        )
        self._refresh_functional_group_analysis()

    def _sync_project_metadata_from_panel(self) -> None:
        if self._project is None:
            return
        self._on_metadata_changed(self._metadata_panel.current_metadata())

    def _open_recent_path(self, path: str) -> None:
        if path.lower().endswith(".irproj"):
            self._load_project_from_path(path)
            return
        self._load_spectrum(path)

    def _load_project_from_path(self, path: str) -> None:
        from pathlib import Path  # noqa: PLC0415

        from storage.project_serializer import ProjectSerializer  # noqa: PLC0415

        project = ProjectSerializer().load(path)
        self._apply_project_to_ui(project, recent_path=path)
        self.statusBar().showMessage(f"Project loaded: {Path(path).name}")

    def _on_metadata_changed(self, metadata) -> None:
        if self._project is None:
            return

        self._project.metadata = metadata
        self._project.updated_at = datetime.now()

        if self._project.spectrum is not None:
            self._project.spectrum.title = metadata.title
            self._project.spectrum.comments = metadata.comments
        if self._project.corrected_spectrum is not None:
            self._project.corrected_spectrum.title = metadata.title
            self._project.corrected_spectrum.comments = metadata.comments

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

    def _on_save_project(self) -> None:
        """Handle File → Save Project action."""
        if self._project is None:
            self.statusBar().showMessage("No project loaded")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save IR Project",
            "",
            "IR Project Files (*.irproj);;JSON files (*.json)",
        )
        if not path:
            return

        try:
            from pathlib import Path  # noqa: PLC0415

            from storage.project_serializer import ProjectSerializer  # noqa: PLC0415

            self._sync_project_metadata_from_panel()
            ProjectSerializer().save(self._project, path)
            self.statusBar().showMessage(f"Project saved: {Path(path).name}")
            self._add_to_recent(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Save Error", f"Failed to save project:\n{e}")

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
                sample_name=Path(path).stem,
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
        from core.spectrum import SpectralUnit  # noqa: PLC0415
        from processing.peak_detection import detect_peaks  # noqa: PLC0415

        spectrum = self._project.corrected_spectrum or self._project.spectrum
        invert = spectrum.is_dip_spectrum
        if invert:
            prominence = 1.0  # dip-type spectra span 0-100 range
        elif spectrum.y_unit == SpectralUnit.BASELINE_CORRECTED:
            prominence = 1.0  # corrected signal in %T-scale (0-100 range)
        else:
            prominence = 0.05  # absorbance — peaks in 0-2 range, skip minor noise
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

        self._spectrum_widget.set_spectrum(self._project.corrected_spectrum)
        self._refresh_functional_group_analysis()
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
            self._export_csv()
        elif format_choice == "xlsx":
            self._export_xlsx()

    def _export_pdf(self, report_options=None) -> bool:
        """Export the current project to a PDF report."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export PDF Report",
            "",
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

        try:
            builder = ReportBuilder()
            builder.build_with_options(self._project, Path(path), report_options)
            self.statusBar().showMessage(f"PDF exported: {Path(path).name}")
            return True
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Export Error", f"Failed to export PDF:\n{e}")
            return False

    def _export_csv(self) -> None:
        """Export peaks to a CSV file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            "",
            "CSV Files (*.csv);;Text Files (*.txt)",
        )
        if not path:
            return

        from pathlib import Path  # noqa: PLC0415

        from file_io.csv_exporter import CSVExporter  # noqa: PLC0415

        try:
            spectrum = self._project.corrected_spectrum or self._project.spectrum
            CSVExporter().export(self._project.peaks, Path(path), spectrum)
            self.statusBar().showMessage(f"CSV exported: {Path(path).name}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Export Error", f"Failed to export CSV:\n{e}")

    def _export_xlsx(self) -> None:
        """Export peaks and spectrum to an Excel file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Excel",
            "",
            "Excel Files (*.xlsx)",
        )
        if not path:
            return

        from pathlib import Path  # noqa: PLC0415

        from file_io.xlsx_exporter import XLSXExporter  # noqa: PLC0415

        try:
            spectrum = self._project.corrected_spectrum or self._project.spectrum
            XLSXExporter().export(self._project.peaks, Path(path), spectrum)
            self.statusBar().showMessage(f"Excel exported: {Path(path).name}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Export Error", f"Failed to export Excel:\n{e}")

    def _on_peak_selected(self, peak) -> None:
        """Update status bar and highlight matching presets when a peak is selected."""
        self.statusBar().showMessage(
            f"Peak: {peak.position:.2f} cm\u207b\u00b9  |  {peak.intensity:.4f}"
        )
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

    def _on_vibration_label_removed(self, peak: object, label_str: str) -> None:
        """Remove a single vibration label that the user deleted from the peak table cell."""
        if self._project is None:
            return
        from core.commands import RemovePresetCommand  # noqa: PLC0415
        from core.peak import Peak as PeakType  # noqa: PLC0415
        from core.vibration_presets import VibrationPreset  # noqa: PLC0415

        p = peak  # type: ignore[assignment]
        if not isinstance(p, PeakType):
            return
        if label_str not in p.vibration_labels:
            return
        idx = p.vibration_labels.index(label_str)
        db_id = p.vibration_ids[idx] if idx < len(p.vibration_ids) else None
        stub_preset = VibrationPreset(
            name=label_str,
            typical_range_min=0.0,
            typical_range_max=0.0,
            db_id=db_id,
        )
        self._undo_stack.push(RemovePresetCommand(p, stub_preset))
        self._refresh_peak_views(p)

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

    def _on_preset_clicked_for_assign(self, preset) -> None:
        """Store preset as pending — next peak click in viewer will assign it."""
        self._pending_preset = preset
        self.statusBar().showMessage(
            f'Click a peak to assign: "{preset.name}" — or double-click preset to assign to selected row'
        )

    def _on_peak_selected_in_viewer(self, peak) -> None:
        """Select peak in table and highlight presets when user clicks a peak in the chart.

        If a preset is pending (clicked in VibrationPanel), assign it immediately.
        """
        status_msg = f"Peak: {peak.position:.2f} cm\u207b\u00b9  |  {peak.intensity:.4f}"

        if self._pending_preset is not None and self._project is not None:
            # Quick-assign: assign pending preset to clicked peak
            from core.commands import AssignPresetCommand  # noqa: PLC0415

            preset = self._pending_preset
            self._pending_preset = None  # consume — next peak click won't re-assign
            self._undo_stack.push(AssignPresetCommand(peak, preset))
            self._refresh_peak_views(peak)
            status_msg = f'Assigned "{preset.name}" to {peak.position:.1f} cm\u207b\u00b9'

        # Always select in table and highlight matching vibrations
        self._peak_table.select_peak(peak)
        self._vibration_panel.highlight_for_peak(peak.position)
        self._vibration_panel.set_active_peak(peak)
        self._set_functional_group_active_peak(peak)
        self.statusBar().showMessage(status_msg)

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
        if self._project is None:
            return
        peak = self._peak_table.selected_peak()
        if peak is None:
            return
        from core.commands import DeletePeakCommand  # noqa: PLC0415

        self._undo_stack.push(DeletePeakCommand(self._project, peak))
        self._refresh_peak_views()
        self.statusBar().showMessage(f"Deleted peak at {peak.position:.1f} cm\u207b\u00b9")

    def _on_delete_peak_object(self, peak: object) -> None:
        """Delete a specific peak object (emitted from shift+click on label)."""
        if self._project is None:
            return
        from core.commands import DeletePeakCommand  # noqa: PLC0415

        self._undo_stack.push(DeletePeakCommand(self._project, peak))
        self._refresh_peak_views()

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
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.completed.connect(self._on_match_spectrum_completed)
        worker.failed.connect(self._on_match_spectrum_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_reference_search_thread_finished)
        thread.started.connect(
            lambda: QMetaObject.invokeMethod(worker, "run", Qt.ConnectionType.QueuedConnection)
        )
        self._reference_search_thread = thread
        self._set_match_search_busy(True)
        thread.start()

    def _execute_match_spectrum_search(self, spectrum) -> None:
        """Run spectral matching synchronously (used for tests/in-memory DB)."""
        try:
            outcome = self._reference_library_service.search_spectrum(
                spectrum,
                top_n=self._MATCH_RESULTS_LIMIT,
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Match Error", f"Matching failed:\n{e}")
            return
        self._apply_match_spectrum_outcome(outcome)

    def _on_match_spectrum_completed(self, outcome) -> None:
        """Apply background search results once the worker finishes."""
        self._apply_match_spectrum_outcome(outcome)

    def _on_match_spectrum_failed(self, message: str) -> None:
        """Show a background search failure to the user."""
        self.statusBar().showMessage("Matching failed")
        QMessageBox.critical(self, "Match Error", f"Matching failed:\n{message}")

    def _on_reference_search_thread_finished(self) -> None:
        """Reset UI state after a background reference search completes."""
        self._reference_search_thread = None
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
            self._match_results_panel.set_results([])
            return

        self._last_search_refs = list(outcome.references)
        self._match_results_panel.set_results(list(outcome.results))
        if outcome.imported_summary is not None and outcome.imported_summary.imported > 0:
            self.statusBar().showMessage(
                "Imported "
                f"{outcome.imported_summary.imported} bundled references and matched "
                f"against {outcome.reference_count} spectra"
            )
        else:
            self.statusBar().showMessage(f"Matched against {outcome.reference_count} references")

    def _set_match_search_busy(self, busy: bool) -> None:
        """Toggle the match action while a background reference search is running."""
        if self._toolbar._match_action is not None:
            self._toolbar._match_action.setEnabled(not busy)
        if busy:
            self.statusBar().showMessage("Matching spectrum against reference library…")

    def _on_match_candidate_selected(self, result) -> None:
        """Show the selected reference spectrum as overlay."""
        from core.spectrum import Spectrum  # noqa: PLC0415

        ref = self._reference_library_service.get_reference_spectrum(int(result.ref_id))
        if ref is None:
            return
        overlay = Spectrum(
            wavenumbers=ref["wavenumbers"],
            intensities=ref["intensities"],
            title=ref["name"],
        )
        self._spectrum_widget.set_overlay_spectra([overlay])

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

        self._undo_stack.push(AssignPresetCommand(peak, preset))
        self._refresh_peak_views(peak)
        self.statusBar().showMessage(
            f'Assigned suggested vibration "{preset.name}" to {peak.position:.1f} cm\u207b\u00b9'
        )

    def _refresh_functional_group_analysis(self) -> None:
        """Recompute functional-group scores from the current project spectrum."""
        if self._project is None or self._project.spectrum is None:
            self._functional_group_panel.clear()
            self._spectrum_widget.set_diagnostic_regions([])
            return

        from processing.functional_group_scoring import score_functional_groups  # noqa: PLC0415

        analysis = score_functional_groups(
            self._project.spectrum,
            self._project.corrected_spectrum,
        )
        self._functional_group_panel.set_results(list(analysis.results))
        self._set_functional_group_active_peak(self._peak_table.selected_peak())

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

        self._peak_table.set_peaks(self._project.peaks)
        self._spectrum_widget.set_peaks(self._project.peaks)

        active_peak = None
        if preferred_peak is not None and any(
            existing_peak is preferred_peak for existing_peak in self._project.peaks
        ):
            self._peak_table.select_peak(preferred_peak)
            active_peak = preferred_peak
        else:
            active_peak = self._peak_table.selected_peak()

        if active_peak is not None:
            self._vibration_panel.highlight_for_peak(active_peak.position)
            self._vibration_panel.set_active_peak(active_peak)
        else:
            self._vibration_panel.clear_peak_context()
        self._set_functional_group_active_peak(active_peak)

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
