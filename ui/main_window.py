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

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut, QUndoStack
from PySide6.QtWidgets import (
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
from ui.metadata_panel import MetadataPanel
from ui.molecule_widget import MoleculeWidget
from ui.peak_table_widget import PeakTableWidget
from ui.spectrum_widget import SpectrumWidget
from ui.toolbar import MainToolbar
from ui.vibration_panel import VibrationPanel


class MainWindow(QMainWindow):
    """Main application window with dockable analysis panels."""

    def __init__(
        self,
        db: Database,
        settings: Settings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._settings = settings
        self._project = None
        self._recent_menu: QMenu | None = None
        self._undo_stack = QUndoStack(self)
        self._last_search_refs: list = []  # cached from last _on_match_spectrum call
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
        self._vibration_panel = VibrationPanel(self)
        left_dock = QDockWidget("Vibration Presets", self)
        left_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        left_dock.setFeatures(dock_features)
        left_dock.setWidget(self._vibration_panel)
        left_dock.setMinimumWidth(280)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left_dock)

        # Bottom dock: Peaks
        self._peak_table = PeakTableWidget(self)
        bottom_dock = QDockWidget("Peaks", self)
        bottom_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        bottom_dock.setFeatures(dock_features)
        bottom_dock.setWidget(self._peak_table)
        bottom_dock.setMinimumHeight(200)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, bottom_dock)

        # Right dock: Metadata
        self._metadata_panel = MetadataPanel(self)
        right_dock = QDockWidget("Metadata", self)
        right_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        right_dock.setFeatures(dock_features)
        right_dock.setWidget(self._metadata_panel)
        right_dock.setMinimumWidth(260)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right_dock)

        # Bottom-right dock: Match Results
        from ui.match_results_panel import MatchResultsPanel  # noqa: PLC0415

        self._match_results_panel = MatchResultsPanel(self)
        match_dock = QDockWidget("Match Results", self)
        match_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        match_dock.setFeatures(dock_features)
        match_dock.setWidget(self._match_results_panel)
        match_dock.setMinimumHeight(150)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, match_dock)
        self.tabifyDockWidget(right_dock, match_dock)  # tab with Metadata panel

        # Right dock: Molecule Structure
        self._molecule_widget = MoleculeWidget(self)
        structure_dock = QDockWidget("Structure", self)
        structure_dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        structure_dock.setFeatures(dock_features)
        structure_dock.setWidget(self._molecule_widget)
        structure_dock.setMinimumWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, structure_dock)
        self.tabifyDockWidget(right_dock, structure_dock)  # tab with Metadata panel

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
        spectrum = (
            self._project.corrected_spectrum
            if self._project.corrected_spectrum is not None
            else self._project.spectrum
        )
        self._spectrum_widget.set_spectrum(spectrum)
        self._peak_table.set_peaks(self._project.peaks)

    def _connect_signals(self) -> None:
        """Wire up inter-component signals."""
        self._spectrum_widget.peak_clicked.connect(self._on_peak_clicked)
        self._spectrum_widget.peak_selected_in_viewer.connect(self._on_peak_selected_in_viewer)
        self._peak_table.peak_selected.connect(self._on_peak_selected)
        self._vibration_panel.preset_selected.connect(self._on_preset_selected)
        self._match_results_panel.candidate_selected.connect(self._on_match_candidate_selected)
        self._match_results_panel.import_reference.connect(self._on_import_reference)

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

        from pathlib import Path  # noqa: PLC0415

        from storage.project_serializer import ProjectSerializer  # noqa: PLC0415

        try:
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

        from pathlib import Path  # noqa: PLC0415

        from storage.project_serializer import ProjectSerializer  # noqa: PLC0415

        try:
            project = ProjectSerializer().load(path)
            self._project = project
            self._undo_stack.clear()
            self._add_to_recent(path)

            display_spectrum = project.corrected_spectrum or project.spectrum
            if display_spectrum is not None:
                self._spectrum_widget.set_spectrum(display_spectrum)

            self._peak_table.set_peaks(project.peaks)

            if project.spectrum is not None:
                from core.metadata import SpectrumMetadata  # noqa: PLC0415

                spectrum = project.spectrum
                metadata = SpectrumMetadata(
                    title=spectrum.title,
                    sample_name=Path(spectrum.source_path).stem if spectrum.source_path else "",
                    operator="",
                    instrument=str(spectrum.extra_metadata.get("instrument_serial", "")),
                    acquired_at=spectrum.acquired_at,
                    resolution=spectrum.extra_metadata.get("resolution_cm"),
                    scans=None,
                    comments=spectrum.comments,
                )
                self._metadata_panel.set_metadata(metadata)

            self.statusBar().showMessage(f"Project loaded: {Path(path).name}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Open Error", f"Failed to open project:\n{e}")

    def _load_spectrum(self, path: str) -> None:
        """Load a spectrum file and update the UI."""
        from pathlib import Path  # noqa: PLC0415

        from core.metadata import SpectrumMetadata  # noqa: PLC0415
        from core.project import Project  # noqa: PLC0415
        from file_io.format_registry import FormatRegistry  # noqa: PLC0415

        try:
            registry = FormatRegistry()
            spectrum = registry.read(Path(path))
            self._project = Project(name=Path(path).stem, spectrum=spectrum)
            self._undo_stack.clear()
            self._add_to_recent(path)

            # Update spectrum viewer
            self._spectrum_widget.set_spectrum(spectrum)

            # Update metadata panel
            metadata = SpectrumMetadata(
                title=spectrum.title,
                sample_name=Path(path).stem,
                operator="",
                instrument=str(spectrum.extra_metadata.get("instrument_serial", "")),
                acquired_at=spectrum.acquired_at,
                resolution=spectrum.extra_metadata.get("resolution_cm"),
                scans=None,
                comments=spectrum.comments,
            )
            self._metadata_panel.set_metadata(metadata)

            # Load vibration presets from DB
            if hasattr(self._db, "get_vibration_presets"):
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
                    )
                    for row in raw_presets
                ]
                self._vibration_panel.set_presets(presets)

            self.statusBar().showMessage(f"Loaded: {Path(path).name} ({spectrum.n_points} points)")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to load spectrum:\n{e}")

    def _on_tool_mode_changed(self, mode: str) -> None:
        """Switch tool mode in SpectrumWidget."""
        self._spectrum_widget.set_tool_mode(mode)

    def _on_peak_clicked(self, wavenumber: float, intensity: float) -> None:
        """Add a manually clicked peak to the project."""
        if self._project is None:
            return
        from core.commands import AddPeakCommand  # noqa: PLC0415
        from core.peak import Peak  # noqa: PLC0415

        peak = Peak(position=wavenumber, intensity=intensity)
        cmd = AddPeakCommand(self._project, peak)
        self._undo_stack.push(cmd)
        self._peak_table.set_peaks(self._project.peaks)
        self._spectrum_widget.set_peaks(self._project.peaks)

    def _on_detect_peaks(self) -> None:
        """Run automatic peak detection on the loaded spectrum."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage("No spectrum loaded")
            return
        from core.spectrum import SpectralUnit  # noqa: PLC0415
        from processing.peak_detection import detect_peaks  # noqa: PLC0415

        spectrum = self._project.corrected_spectrum or self._project.spectrum
        _dip_units = (SpectralUnit.TRANSMITTANCE, SpectralUnit.REFLECTANCE, SpectralUnit.SINGLE_BEAM)
        invert = spectrum.y_unit in _dip_units
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
        self._peak_table.set_peaks(self._project.peaks)
        self._spectrum_widget.set_peaks(self._project.peaks)
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
        _dip_units = (SpectralUnit.TRANSMITTANCE, SpectralUnit.REFLECTANCE, SpectralUnit.SINGLE_BEAM)
        use_upper_hull = source_spectrum.y_unit in _dip_units
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
        self.statusBar().showMessage("Baseline corrected (Ctrl+Z to undo)")

    def _on_export(self) -> None:
        """Show export dialog and export in selected format."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage("No spectrum loaded")
            return

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

        from reporting.report_builder import ReportBuilder  # noqa: PLC0415

        try:
            builder = ReportBuilder()
            if report_options is None:
                builder.build(self._project, Path(path))
            else:
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
        self._molecule_widget.set_smiles(peak.smiles)

    def _on_peak_selected_in_viewer(self, peak) -> None:
        """Select peak in table and highlight presets when user clicks a peak in the chart."""
        self._peak_table.select_peak(peak)
        self._vibration_panel.highlight_for_peak(peak.position)
        self._molecule_widget.set_smiles(peak.smiles)
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
        self._peak_table.set_peaks(self._project.peaks)
        self._spectrum_widget.set_peaks(self._project.peaks)
        self.statusBar().showMessage("Peaks cleared")

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
        self._peak_table.set_peaks(self._project.peaks)
        self._spectrum_widget.set_peaks(self._project.peaks)
        self.statusBar().showMessage(
            f'Assigned "{preset.name}" to peak at {peak.position:.1f} cm\u207b\u00b9'
        )

    def _on_delete_peak(self) -> None:
        """Delete the currently selected peak."""
        if self._project is None:
            return
        peak = self._peak_table.selected_peak()
        if peak is None:
            return
        from core.commands import DeletePeakCommand  # noqa: PLC0415

        self._undo_stack.push(DeletePeakCommand(self._project, peak))
        self._peak_table.set_peaks(self._project.peaks)
        self._spectrum_widget.set_peaks(self._project.peaks)
        self.statusBar().showMessage(f"Deleted peak at {peak.position:.1f} cm\u207b\u00b9")

    def _on_match_spectrum(self) -> None:
        """Run spectral matching against the reference database."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage("No spectrum loaded")
            return

        from matching.search_engine import SearchEngine  # noqa: PLC0415

        try:
            refs = (
                self._db.get_reference_spectra()
                if hasattr(self._db, "get_reference_spectra")
                else []
            )
            if not refs:
                self.statusBar().showMessage("No reference spectra in database. Import some first.")
                return

            self._last_search_refs = refs  # cache for candidate selection overlay
            spectrum = self._project.corrected_spectrum or self._project.spectrum
            engine = SearchEngine()
            engine.load_references(refs)
            results = engine.search(spectrum.wavenumbers, spectrum.intensities, top_n=10)
            self._match_results_panel.set_results(results)
            self.statusBar().showMessage(f"Matched against {engine.n_references} references")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Match Error", f"Matching failed:\n{e}")

    def _on_match_candidate_selected(self, result) -> None:
        """Show the selected reference spectrum as overlay."""
        from core.spectrum import Spectrum  # noqa: PLC0415

        ref = next((r for r in self._last_search_refs if r["id"] == result.ref_id), None)
        if ref is None:
            return
        overlay = Spectrum(
            wavenumbers=ref["wavenumbers"],
            intensities=ref["intensities"],
            title=ref["name"],
        )
        self._spectrum_widget.set_overlay_spectra([overlay])

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
            action.triggered.connect(lambda checked=False, p=path: self._load_spectrum(p))

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
        from ui.dialogs.reference_library_dialog import ReferenceLibraryDialog  # noqa: PLC0415

        dlg = ReferenceLibraryDialog(self._db, parent=self)
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
