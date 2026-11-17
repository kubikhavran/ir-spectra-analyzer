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

from PySide6.QtCore import QByteArray, QEvent, QMetaObject, Qt, QThread, QTimer, Signal
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
    QTabWidget,
    QTextEdit,
    QWidget,
)

from app.report_presets import ReportPresetManager
from processing.consensus_analysis import build_consensus_analysis
from storage.database import Database
from storage.settings import Settings
from ui import i18n, theme
from ui.consensus_panel import ConsensusPanel
from ui.functional_group_panel import FunctionalGroupPanel
from ui.i18n import tr
from ui.metadata_panel import MetadataPanel
from ui.molecule_widget import MoleculeWidget
from ui.peak_table_widget import PeakTableWidget
from ui.spectrum_widget import SpectrumWidget
from ui.toolbar import MainToolbar
from ui.vibration_panel import VibrationPanel
from ui.vibration_text_edit import VibrationTextEditDialog
from ui.welcome_overlay import WelcomeOverlay

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
    #: Asks the controller to open one more dropped file — it decides whether
    #: that needs another window.
    open_path_requested = Signal(str)
    #: The user picked another language / appearance. When the controller
    #: listens (``enable_live_switching``) it rebuilds the windows at once;
    #: a window on its own falls back to "applies on the next start".
    language_change_requested = Signal()
    appearance_change_requested = Signal()

    #: File types the window opens when dropped on it or picked from "recent".
    _OPENABLE_SUFFIXES = (".spa", ".jdx", ".dx", ".irproj")

    _MATCH_RESULTS_LIMIT = 20
    _ASSIGNMENT_TRANSFER_TOLERANCE = 8.0  # cm⁻¹ window for copying assignments
    _DETECT_UNDO_TEXT = "Detect peaks"
    # A detected peak this close to an already assigned one is the same band.
    _DETECT_KEEP_TOLERANCE = 4.0  # cm⁻¹

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
        self._live_switching = False
        self._closing_for_rebuild = False
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
        self._setup_welcome()
        self.setAcceptDrops(True)

        delete_sc = QShortcut(QKeySequence.StandardKey.Delete, self)
        delete_sc.activated.connect(self._on_delete_peak)

        self._layout_restored = False
        i18n.translate_tree(self)
        # Remembered after everything exists, so "Reset Layout" has the
        # arrangement the application ships with to go back to.
        self._default_window_state = self.saveState()
        self._restore_window_layout()
        self._update_status_chips()

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

        open_action = file_menu.addAction("&Open Spectrum...")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_file)

        open_project_action = file_menu.addAction("Open &Project...")
        open_project_action.triggered.connect(self._on_open_project)

        save_project_action = file_menu.addAction("&Save Project")
        save_project_action.setShortcut("Ctrl+S")
        save_project_action.setToolTip(
            "Save to the project file already open; asks for a name the first time"
        )
        save_project_action.triggered.connect(self._on_save_project_quick)

        save_as_action = file_menu.addAction("Save Project &As...")
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self._on_save_project)

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
        edit_menu.addSeparator()
        copy_image_action = edit_menu.addAction(tr("Copy Spectrum &Image"))
        copy_image_action.setShortcut("Ctrl+Shift+C")
        copy_image_action.setToolTip(
            tr("Copy the spectrum, as drawn in the report, to paste into a protocol or slides")
        )
        copy_image_action.triggered.connect(self._on_copy_spectrum_image)
        copy_ir_action = edit_menu.addAction(tr("Copy IR &Text"))
        copy_ir_action.triggered.connect(lambda: self._peak_table.copy_ir_text())

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
        self._language_menu = QMenu("&Language", self)
        self._setup_language_menu()
        self._appearance_menu = QMenu("&Appearance", self)
        self._setup_appearance_menu()

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
        self._toolbar.set_sensitivity(self._settings.get("peak_sensitivity"))
        self._toolbar.sensitivity_changed.connect(self._on_sensitivity_changed)
        self._toolbar.save_requested.connect(self._on_save_project_quick)
        self._toolbar.undo_requested.connect(self._undo_stack.undo)
        self._toolbar.redo_requested.connect(self._undo_stack.redo)
        for stack_signal in (
            self._undo_stack.canUndoChanged,
            self._undo_stack.canRedoChanged,
            self._undo_stack.undoTextChanged,
            self._undo_stack.redoTextChanged,
        ):
            stack_signal.connect(lambda *_: self._sync_history_buttons())
        self._toolbar.correct_baseline.connect(self._on_correct_baseline)
        self._toolbar.arrange_labels.connect(self._on_arrange_peak_labels)
        self._toolbar.match_spectrum.connect(self._on_match_spectrum)

    def _sync_history_buttons(self) -> None:
        """Keep the toolbar's Undo/Redo buttons in step with the undo stack."""
        try:
            self._toolbar.set_history_state(
                can_undo=self._undo_stack.canUndo(),
                can_redo=self._undo_stack.canRedo(),
                undo_text=self._undo_stack.undoText(),
                redo_text=self._undo_stack.redoText(),
            )
        except RuntimeError:
            # Signals can still arrive while Qt is tearing the window down.
            return

    def _setup_language_menu(self) -> None:
        """View → Language: system / English / Čeština."""
        from PySide6.QtGui import QActionGroup  # noqa: PLC0415

        stored = self._settings.get("language")
        current = stored if stored in (i18n.ENGLISH, i18n.CZECH) else i18n.SYSTEM
        group = QActionGroup(self._language_menu)
        group.setExclusive(True)
        for code, label in i18n.LANGUAGES:
            action = self._language_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(code == current)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, c=code: self._on_language_chosen(c))

    def _on_language_chosen(self, code: str) -> None:
        """Remember the language and switch to it (at once when the controller can)."""
        stored = None if code == i18n.SYSTEM else code
        unchanged = self._settings.get("language") == stored
        self._settings.set("language", stored)
        if self._live_switching:
            if not unchanged or i18n.resolve_language(stored) != i18n.language():
                self.language_change_requested.emit()
            return
        QMessageBox.information(
            self,
            "Language / Jazyk",
            "The language changes the next time the application starts.\n"
            "Jazyk se změní při příštím spuštění aplikace.",
        )

    def _build_language_switch(self) -> QWidget:
        """CZ | EN buttons in the corner of the status bar — one click switches."""
        from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QToolButton  # noqa: PLC0415

        box = QWidget(self)
        box.setObjectName("languageSwitch")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(6, 0, 2, 0)
        layout.setSpacing(0)
        group = QButtonGroup(box)
        group.setExclusive(True)
        self._language_buttons: dict[str, QToolButton] = {}
        for code, text, tip in (
            (i18n.CZECH, "CZ", "Čeština"),
            (i18n.ENGLISH, "EN", "English"),
        ):
            button = QToolButton(box)
            button.setObjectName("languageSwitchButton")
            button.setText(text)
            button.setToolTip(f"{tip} — Jazyk / Language")
            button.setCheckable(True)
            button.setChecked(i18n.language() == code)
            button.setAutoRaise(True)
            button.clicked.connect(lambda _checked=False, c=code: self._on_language_chosen(c))
            group.addButton(button)
            layout.addWidget(button)
            self._language_buttons[code] = button
        box.setStyleSheet(
            f"QToolButton#languageSwitchButton {{ padding: 1px 7px; font-weight: 600;"
            f" color: {theme.TEXT_MUTED}; border: 1px solid {theme.BORDER}; }}"
            f"QToolButton#languageSwitchButton:checked {{ color: {theme.ON_ACCENT};"
            f" background: {theme.ACCENT}; border-color: {theme.ACCENT}; }}"
        )
        return box

    def enable_live_switching(self) -> None:
        """Called by the controller: language/appearance changes rebuild the windows."""
        self._live_switching = True

    def is_busy(self) -> bool:
        """Whether a background search would be cut off by rebuilding the window."""
        return self._reference_search_thread is not None

    def adopt_from(self, old: MainWindow) -> None:
        """Take over another window's place and analysis (language/theme rebuild).

        The project object itself moves over, so peaks, assignments, the
        structure and unsaved edits stay; only the undo history starts afresh.
        """
        self.restoreGeometry(old.saveGeometry())
        if not old.isMaximized():
            self.resize(old.size())
            self.move(old.pos())
        self.restoreState(old.saveState())
        project = old._project
        if project is None:
            return
        dirty = old._has_unsaved_changes()
        revision = old._project_revision
        project_path = old._current_project_path
        self._apply_project_to_ui(project)
        self._current_project_path = project_path
        self._non_undo_dirty = dirty
        self._project_revision = revision
        self._update_window_title()

    def close_for_rebuild(self) -> None:
        """Close without the unsaved-work prompt: the work lives on in the new window."""
        self._closing_for_rebuild = True
        self.close()

    def _setup_appearance_menu(self) -> None:
        """View → Appearance: dark / light / follow the system."""
        from PySide6.QtGui import QActionGroup  # noqa: PLC0415

        stored = self._settings.get("appearance")
        known = [code for code, _label in theme.APPEARANCES]
        current = stored if isinstance(stored, str) and stored in known else theme.DARK_MODE
        group = QActionGroup(self._appearance_menu)
        group.setExclusive(True)
        for code, label in theme.APPEARANCES:
            action = self._appearance_menu.addAction(tr(label))
            action.setCheckable(True)
            action.setChecked(code == current)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, c=code: self._on_appearance_chosen(c))

    def _on_appearance_chosen(self, code: str) -> None:
        """Remember the appearance and switch to it (at once when the controller can)."""
        if self._settings.get("appearance") == code:
            return
        self._settings.set("appearance", code)
        if self._live_switching:
            self.appearance_change_requested.emit()
            return
        QMessageBox.information(
            self,
            tr("Appearance"),
            tr("The new appearance is used the next time the application starts."),
        )

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
        # Grouped by type unless the user switched back to the plain
        # wavenumber order; the choice is remembered.
        self._vibration_panel.set_view_mode(self._settings.get("vibration_list_mode"))
        self._vibration_panel.view_mode_changed.connect(
            lambda mode: self._settings.set("vibration_list_mode", mode)
        )
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
        for name, dock in (
            ("dockVibration", self._dock_vibration),
            ("dockPeaks", self._dock_peaks),
            ("dockMetadata", self._dock_metadata),
            ("dockMatch", self._dock_match),
            ("dockFunctionalGroups", self._dock_functional_groups),
            ("dockConsensus", self._dock_consensus),
            ("dockStructure", self._dock_structure),
        ):
            dock.setObjectName(name)  # saveState/restoreState identify docks by name
            self._view_menu.addAction(dock.toggleViewAction())
        self._view_menu.addSeparator()
        reset_layout_action = self._view_menu.addAction("&Reset Layout")
        reset_layout_action.setToolTip("Put every panel back where it was when first installed")
        reset_layout_action.triggered.connect(self._on_reset_layout)
        self._view_menu.addMenu(self._language_menu)
        self._view_menu.addMenu(self._appearance_menu)

        self.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)
        # The right-hand tabs follow the order of the work; the first one —
        # what was measured — is the one in front when the window opens, not
        # the still-empty structure panel that happened to be added last.
        self._dock_metadata.raise_()
        QTimer.singleShot(0, self._raise_first_tab)

        # Band markers belong to the Functional Groups tab: they are drawn
        # while that tab is in front and stay out of the spectrum otherwise.
        self._fg_regions_checked = True
        self._dock_functional_groups.visibilityChanged.connect(
            lambda _visible: self._sync_functional_group_regions()
        )

        self._reload_vibration_presets()
        self._load_functional_group_tags()

    def _raise_first_tab(self) -> None:
        try:
            if not self._layout_restored:
                # Wide enough for all five tab titles to be read in full. Only
                # for the stock arrangement — a remembered layout is the user's.
                self.resizeDocks([self._dock_metadata], [500], Qt.Orientation.Horizontal)
                self.resizeDocks([self._dock_vibration], [300], Qt.Orientation.Horizontal)
            self._dock_metadata.raise_()
            self._sync_functional_group_regions()
        except RuntimeError:  # window already closed (tests, quick open/close)
            return

    def _functional_group_dock_in_front(self) -> bool:
        """True while the Functional Groups panel is actually on screen."""
        if not self.isVisible():
            return True  # not shown yet: nothing is hidden behind another tab
        return not self._dock_functional_groups.visibleRegion().isEmpty()

    def _sync_functional_group_regions(self) -> None:
        """Draw the band markers only while their panel is in front and switched on."""
        try:
            self._spectrum_widget.set_diagnostic_regions_visible(
                self._fg_regions_checked and self._functional_group_dock_in_front()
            )
        except RuntimeError:
            return

    def _on_reset_layout(self) -> None:
        """View → Reset Layout."""
        self._layout_restored = False
        self.restoreState(self._default_window_state)
        self._raise_first_tab()
        self.statusBar().showMessage(tr("Panel layout reset"))

    def _restore_window_layout(self) -> None:
        """Bring back the window size and panel arrangement of the last session."""
        self._layout_restored = False
        for key in ("window_geometry", "window_state"):
            stored = self._settings.get(key)
            if not isinstance(stored, str) or not stored:
                continue
            try:
                blob = QByteArray.fromBase64(stored.encode("ascii"))
                restored = (
                    self.restoreGeometry(blob)
                    if key == "window_geometry"
                    else self.restoreState(blob)
                )
            except Exception:  # noqa: BLE001 — a stale layout must never block start-up
                continue
            if restored:
                self._layout_restored = True

    def _save_window_layout(self) -> None:
        """Remember the window size and panel arrangement for the next start."""
        try:
            self._settings.set(
                "window_geometry", bytes(self.saveGeometry().toBase64().data()).decode("ascii")
            )
            self._settings.set(
                "window_state", bytes(self.saveState().toBase64().data()).decode("ascii")
            )
        except Exception:  # noqa: BLE001 — remembering the layout is best-effort
            pass

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
                seed_name=str(row.get("seed_name") or ""),
            )
            for row in raw_presets
        ]
        self._vibration_presets_cache = presets
        self._vibration_panel.set_presets(presets)
        self._refresh_functional_group_assignment_preview()

    def _setup_statusbar(self) -> None:
        """Status bar: transient messages left, the standing facts right."""
        self._status_hidden_labels = QLabel("")
        self._status_hidden_labels.setProperty("chip", "true")
        self._status_hidden_labels.setToolTip(
            tr("Labels of weaker peaks are hidden where they would overlap. Zoom in to see them.")
        )
        self._status_peaks = QLabel("")
        self._status_unit = QLabel("")
        self._status_unit.setProperty("chip", "true")
        self._status_baseline = QLabel(tr("Baseline corrected"))
        self._status_baseline.setProperty("chip", "true")
        self._status_cursor = QLabel(tr("Ready"))
        self._status_cursor.setMinimumWidth(190)
        self._status_cursor.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        for widget in (
            self._status_hidden_labels,
            self._status_peaks,
            self._status_baseline,
            self._status_unit,
            self._status_cursor,
        ):
            self.statusBar().addPermanentWidget(widget)
        self.statusBar().addPermanentWidget(self._build_language_switch())

        self._spectrum_widget.cursor_moved.connect(
            lambda wn, intensity: self._status_cursor.setText(
                self._spectrum_widget.cursor_readout(wn, intensity)
            )
        )
        self._spectrum_widget.hidden_labels_changed.connect(
            lambda _count: self._update_status_chips()
        )
        self._spectrum_widget._unit_combo.currentIndexChanged.connect(
            lambda _index: self._update_status_chips()
        )

        self._undo_stack.indexChanged.connect(self._on_undo_redo)
        self._undo_stack.cleanChanged.connect(lambda _clean: self._update_window_title())

    def _update_dock_badges(self) -> None:
        """Show live peak/assignment counts, match counts, and structure indicator on dock tabs."""
        from core.peak_assignments import peak_has_assignment  # noqa: PLC0415

        project = self._project
        peaks = project.peaks if project is not None else []
        total_peaks = len(peaks)
        if total_peaks > 0:
            assigned_peaks = sum(1 for p in peaks if peak_has_assignment(p))
            badge = (
                f"{total_peaks} \u00b7 {assigned_peaks}\u2713"
                if assigned_peaks > 0
                else f"{total_peaks}"
            )
            self._dock_peaks.setWindowTitle(f"{tr('Peaks')} ({badge})")
        else:
            self._dock_peaks.setWindowTitle(tr("Peaks"))

        match_count = len(self._current_match_results)
        if match_count > 0:
            self._dock_match.setWindowTitle(f"{tr('Match Results')} ({match_count})")
        else:
            self._dock_match.setWindowTitle(tr("Match Results"))

        has_struct = bool(
            project is not None
            and (project.smiles or getattr(project, "mol_block", "") or project.structure_image)
        )
        self._dock_structure.setWindowTitle(
            f"{tr('Structure')} \u2022" if has_struct else tr("Structure")
        )

    def _update_status_chips(self) -> None:
        """Refresh the standing facts: peaks, unit, baseline state, hidden labels."""
        project = self._project
        spectrum = None
        if project is not None:
            spectrum = project.corrected_spectrum or project.spectrum
        has_spectrum = spectrum is not None

        hidden = self._spectrum_widget.hidden_label_count()
        self._status_hidden_labels.setVisible(has_spectrum and hidden > 0)
        if hidden > 0:
            self._status_hidden_labels.setText(tr("{count} labels hidden").format(count=hidden))

        self._status_peaks.setVisible(has_spectrum)
        self._status_peaks.setText(self._peak_table.summary_text() if has_spectrum else "")

        self._status_baseline.setVisible(
            bool(spectrum is not None and spectrum.is_baseline_corrected)
        )

        self._status_unit.setVisible(has_spectrum)
        if spectrum is not None:
            shown_unit = self._spectrum_widget.display_unit() or spectrum.display_y_unit
            self._status_unit.setText(tr(shown_unit.value))
        self._update_dock_badges()

    def _on_undo_redo(self) -> None:
        """Refresh UI state after undo/redo operations."""
        if self._project is None or self._project.spectrum is None:
            return
        self._project_revision += 1
        # Whatever the status line said described the state before this step.
        self.statusBar().clearMessage()
        preferred_peak = self._peak_table.selected_peak()
        preferred_group_id = self._current_functional_group_id()
        spectrum = (
            self._project.corrected_spectrum
            if self._project.corrected_spectrum is not None
            else self._project.spectrum
        )
        # Keep the user's current zoom/pan — adding a peak while zoomed in must
        # not snap the graph back to the full view.
        curve_changed = spectrum is not self._spectrum_widget.source_spectrum()
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
        if curve_changed:
            # Baseline correction (or its undo) swapped the curve for one on a
            # different Y scale. The wavenumber zoom is still meaningful, the
            # old intensity range is not — keeping it showed an empty plot.
            self._spectrum_widget.fit_y_to_view()
        self._refresh_functional_group_analysis(preferred_group_id=preferred_group_id)
        self._update_window_title()
        self._update_status_chips()

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
            tr("Unsaved Changes"),
            tr("The current project has unsaved changes. Save them before continuing?"),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self._on_save_project_quick()
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
        self._vibration_panel.presets_changed.connect(self._on_vibration_preset_changed)
        self._vibration_panel.preset_remove_requested.connect(self._on_remove_vibration)
        self._peak_table.vibration_edit_requested.connect(self._on_edit_peak_vibration_requested)
        self._peak_table.ir_text_copied.connect(self._on_ir_text_copied)
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
        self._update_welcome()
        self._update_status_chips()

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
            QMessageBox.critical(
                self, tr("Open Error"), tr("Failed to open recent file:") + f"\n{exc}"
            )

    def _load_project_from_path(self, path: str) -> None:
        from pathlib import Path  # noqa: PLC0415

        from storage.project_serializer import ProjectSerializer  # noqa: PLC0415

        if not self._confirm_project_replacement():
            return
        project = ProjectSerializer().load(path)
        self._apply_project_to_ui(project, recent_path=path)
        self._current_project_path = path
        self._mark_project_saved()
        self.statusBar().showMessage(tr("Project loaded: {name}").format(name=Path(path).name))

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
            tr("Open IR Spectrum"),
            self._last_open_dir(),
            "IR spectra (*.spa *.SPA *.jdx *.JDX *.dx *.DX);;"
            "OMNIC SPA Files (*.spa *.SPA);;JCAMP-DX Files (*.jdx *.JDX *.dx *.DX);;"
            "All Files (*)",
        )
        if path:
            self._remember_open_dir(path)
            self._load_spectrum(path)

    def _last_open_dir(self) -> str:
        """Folder the last spectrum/project was opened from, "" when unknown."""
        stored = self._settings.get("last_open_dir")
        if stored and Path(stored).is_dir():
            return str(stored)
        return ""

    def _remember_open_dir(self, path: str) -> None:
        """Persist the folder of a just-opened file for the next open dialog."""
        try:
            self._settings.set("last_open_dir", str(Path(path).parent))
        except Exception:  # noqa: BLE001 — remembering the folder is best-effort
            pass

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

    def _on_save_project_quick(self) -> bool:
        """Handle File → Save Project: write to the open project file, no dialog.

        Falls back to Save As while the project has never been saved, so the
        first Ctrl+S still asks where the file should go.
        """
        if self._project is None:
            self.statusBar().showMessage(tr("No project loaded"))
            return False
        if not self._current_project_path:
            return self._on_save_project()
        return self._save_project_to(self._current_project_path)

    def _on_save_project(self) -> bool:
        """Handle File → Save Project As action."""
        if self._project is None:
            self.statusBar().showMessage(tr("No project loaded"))
            return False

        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Save IR Project"),
            self._current_project_path or self._suggested_save_path(".irproj"),
            "IR Project Files (*.irproj);;JSON files (*.json)",
        )
        if not path:
            return False
        return self._save_project_to(path)

    def _save_project_to(self, path: str) -> bool:
        """Write the project to ``path`` and run the after-save bookkeeping."""
        from pathlib import Path  # noqa: PLC0415

        from storage.project_serializer import ProjectSerializer  # noqa: PLC0415

        project = self._project
        if project is None:
            return False
        try:
            self._sync_project_metadata_from_panel()
            ProjectSerializer().save(project, path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("Save Error"), tr("Failed to save project:") + f"\n{e}")
            return False

        self._current_project_path = path
        self._mark_project_saved()
        self._remember_save_dir(path)
        self.statusBar().showMessage(tr("Project saved: {name}").format(name=Path(path).name))
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
            tr("Open IR Project"),
            self._last_open_dir(),
            "IR Project Files (*.irproj);;JSON files (*.json);;All Files (*)",
        )
        if not path:
            return
        self._remember_open_dir(path)

        try:
            self._load_project_from_path(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("Open Error"), tr("Failed to open project:") + f"\n{e}")

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
            message = f"{base}, {peak_note}"
            # A header that contradicts the curve is the one thing about a load
            # the analyst cannot see for themselves: it flips the axis and puts
            # every peak label on the wrong side of the band.
            unit_warning = spectrum.y_unit_check.warning
            if unit_warning:
                message = f"{message} — ⚠ {unit_warning}"
            self.statusBar().showMessage(message)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", tr("Failed to load spectrum:") + f"\n{e}")

    def _on_tool_mode_changed(self, mode: str) -> None:
        """Switch tool mode in SpectrumWidget."""
        self._spectrum_widget.set_tool_mode(mode)

    def _on_peak_clicked(self, wavenumber: float, intensity: float, click_y: float) -> None:
        """Add a manually clicked peak to the project."""
        if self._project is None:
            return
        from core.commands import AddPeakCommand  # noqa: PLC0415
        from core.peak import Peak  # noqa: PLC0415

        # The click height is in the displayed unit. While the view is converted
        # it cannot be turned into a label offset in the file's own unit, so the
        # label takes the default position instead of a meaningless one.
        converted_view = self._spectrum_widget.is_converted_view()
        peak = Peak(
            position=wavenumber,
            intensity=intensity,
            manual_placement=not converted_view,
            label_offset_x=0.0,
            label_offset_y=0.0 if converted_view else click_y - intensity,
        )
        cmd = AddPeakCommand(self._project, peak)
        self._undo_stack.push(cmd)
        self._refresh_peak_views(peak)

    def _on_detect_peaks(self) -> None:
        """Run automatic peak detection on the loaded spectrum."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage(tr("No spectrum loaded"))
            return
        from processing.peak_detection import default_prominence, detect_peaks  # noqa: PLC0415

        spectrum = self._project.corrected_spectrum or self._project.spectrum
        invert = spectrum.is_dip_spectrum
        sensitivity = self._toolbar.sensitivity()
        prominence = default_prominence(spectrum, sensitivity)
        peaks = detect_peaks(
            spectrum.wavenumbers, spectrum.intensities, invert=invert, prominence=prominence
        )
        # Wrap all additions in a macro so it's a single Ctrl+Z
        self._undo_stack.beginMacro(self._DETECT_UNDO_TEXT)
        from core.commands import AddPeakCommand, DeletePeakCommand  # noqa: PLC0415
        from core.peak_assignments import peak_has_assignment  # noqa: PLC0415

        # A peak that already carries an assignment is work the analyst did by
        # hand. Re-running detection (e.g. after a baseline correction) used to
        # throw all of it away; now only unassigned peaks are replaced.
        kept = [existing for existing in self._project.peaks if peak_has_assignment(existing)]
        for existing in list(self._project.peaks):
            if not any(existing is keeper for keeper in kept):
                self._undo_stack.push(DeletePeakCommand(self._project, existing))
        for peak in peaks:
            if any(
                abs(peak.position - keeper.position) <= self._DETECT_KEEP_TOLERANCE
                for keeper in kept
            ):
                continue  # the assigned peak already marks this band
            self._undo_stack.push(AddPeakCommand(self._project, peak))
        self._arrange_labels_within_macro()
        self._undo_stack.endMacro()
        self._refresh_peak_views()
        self._spectrum_widget.fit_y_to_view()
        message = tr("Detected {count} peaks at sensitivity {level}").format(
            count=len(self._project.peaks), level=sensitivity
        )
        if kept:
            message += " " + tr("({count} assigned kept)").format(count=len(kept))
        self.statusBar().showMessage(message)

    def _arrange_labels_within_macro(self) -> None:
        """Stagger the labels of a fresh detection, as part of the same undo step.

        Detected peaks used to arrive with every label at the default height,
        so a crowded fingerprint region was an unreadable pile until Arrange
        Labels was pressed. Now a detection comes out readable.
        """
        if self._project is None or not self._project.peaks:
            return
        from core.commands import SetPeakLabelPlacementsCommand  # noqa: PLC0415

        # The labels have to exist in the plot before their sizes can be read.
        self._spectrum_widget.set_peaks(self._project.peaks)
        placements = self._spectrum_widget.compute_auto_label_placements()
        if placements:
            self._undo_stack.push(SetPeakLabelPlacementsCommand(placements))

    def _on_sensitivity_changed(self, sensitivity: int) -> None:
        """Remember the sensitivity and, right after a detection, apply it live.

        When the last thing done was Detect Peaks, that detection is replaced by
        one at the new sensitivity, so the slider can be dragged until the
        peak set looks right and the whole thing is still a single undo step.
        Once anything else has been done since (a peak added, an assignment),
        nothing is touched until Detect Peaks is pressed again.
        """
        try:
            self._settings.set("peak_sensitivity", int(sensitivity))
        except Exception:  # noqa: BLE001 — remembering the level is best-effort
            pass
        if self._project is None or self._project.spectrum is None:
            return
        if self._undo_stack.canUndo() and self._undo_stack.undoText() == self._DETECT_UNDO_TEXT:
            self._undo_stack.undo()
            self._on_detect_peaks()
            return
        self.statusBar().showMessage(
            tr("Sensitivity {level} — press Detect Peaks to apply it").format(level=sensitivity)
        )

    def _on_correct_baseline(self) -> None:
        """Apply baseline correction and make it undoable."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage(tr("No spectrum loaded"))
            return

        from core.commands import CorrectBaselineCommand  # noqa: PLC0415
        from core.spectrum import (  # noqa: PLC0415
            BASELINE_CORRECTED_FLAG,
            SpectralUnit,
            Spectrum,
        )
        from processing.baseline import rubber_band_baseline  # noqa: PLC0415

        source_spectrum = self._project.spectrum
        use_upper_hull = source_spectrum.is_dip_spectrum
        corrected_intensities = rubber_band_baseline(
            source_spectrum.wavenumbers,
            source_spectrum.intensities,
            upper=use_upper_hull,
        )

        # A %T baseline is divided out, so the result is still %T (baseline at
        # 100 %) and keeps its unit: overlays, the unit switch, matching and
        # the report all go on working on the familiar scale. Subtracted
        # absorbance keeps the dedicated "Baseline Corrected" unit.
        corrected_unit = (
            source_spectrum.display_y_unit if use_upper_hull else SpectralUnit.BASELINE_CORRECTED
        )
        corrected_spectrum = Spectrum(
            wavenumbers=source_spectrum.wavenumbers.copy(),
            intensities=corrected_intensities,
            title=source_spectrum.title,
            source_path=source_spectrum.source_path,
            acquired_at=source_spectrum.acquired_at,
            y_unit=corrected_unit,
            x_unit=source_spectrum.x_unit,
            comments=source_spectrum.comments,
            extra_metadata={**source_spectrum.extra_metadata, BASELINE_CORRECTED_FLAG: True},
        )

        command = CorrectBaselineCommand(self._project, corrected_spectrum)
        self._undo_stack.push(command)

        self.statusBar().showMessage(tr("Baseline corrected (Ctrl+Z to undo)"))

    def _on_export(self) -> None:
        """Show export dialog and export in selected format."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage(tr("No spectrum loaded"))
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
            self._export_csv(
                include_unassigned=dialog.include_unassigned,
                mode=getattr(dialog, "csv_mode", "combined"),
                decimal_separator=getattr(dialog, "decimal_separator", "."),
            )
        elif format_choice == "image":
            self._export_spectrum_image()
        elif format_choice == "xlsx":
            self._export_xlsx(
                include_unassigned=dialog.include_unassigned,
                include_chart=bool(getattr(dialog, "include_chart", False)),
            )

    def _export_pdf(self, report_options=None) -> bool:
        """Export the current project to a PDF report."""
        project = self._project
        if project is None or project.spectrum is None:
            self.statusBar().showMessage(tr("No spectrum loaded"))
            return False
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Export PDF Report"),
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
        report_project, report_options.peak_label_placements = self._project_as_displayed(project)

        try:
            builder = ReportBuilder()
            builder.build_with_options(report_project, Path(path), report_options)
            self._remember_save_dir(path)
            self.statusBar().showMessage(tr("PDF exported: {name}").format(name=Path(path).name))
            return True
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("Export Error"), tr("Failed to export PDF:") + f"\n{e}")
            return False

    def _project_as_displayed(self, project):
        """Return (project, label placements) matching what the viewer shows.

        The Y range and label positions handed to the report come from the
        plot. While the plot is converted to another unit they are on that
        unit's scale, so the report has to draw the converted curve too —
        pairing them with the stored data flattened the spectrum to a line.
        The saved project itself is never touched.
        """
        from dataclasses import replace  # noqa: PLC0415

        widget = self._spectrum_widget
        placements = {
            id(peak): (label_x, label_y)
            for peak, label_x, label_y in widget.get_peak_label_placements()
        }
        unit = widget.display_unit()
        source = project.corrected_spectrum or project.spectrum
        if not widget.is_converted_view() or unit is None or source is None:
            return project, placements
        converted = source.converted_to(unit)
        if converted is None:
            return project, placements

        shown_peaks = []
        shown_placements: dict[int, tuple[float, float]] = {}
        for peak in project.peaks:
            shown = replace(
                peak,
                intensity=widget.display_intensity(peak.intensity),
                vibration_ids=list(peak.vibration_ids),
                vibration_labels=list(peak.vibration_labels),
                manual_placement=False,
                label_offset_x=0.0,
                label_offset_y=0.0,
            )
            shown_peaks.append(shown)
            if id(peak) in placements:
                shown_placements[id(shown)] = placements[id(peak)]
        shown_project = replace(
            project, spectrum=converted, corrected_spectrum=None, peaks=shown_peaks
        )
        return shown_project, shown_placements

    # Spectrum image (clipboard / PNG / SVG)
    _IMAGE_FIGSIZE = (10.0, 4.6)  # inches; reads well on an A4 page or a slide
    _IMAGE_DPI = 300

    def _render_spectrum_image(self, image_format: str = "png", *, dpi: int | None = None):
        """The spectrum as the report draws it, for the current view; None without one."""
        project = self._project
        if project is None or project.spectrum is None:
            return None
        from reporting.pdf_generator import ReportOptions  # noqa: PLC0415
        from reporting.spectrum_renderer import SpectrumRenderer  # noqa: PLC0415

        shown, placements = self._project_as_displayed(project)
        spectrum = shown.corrected_spectrum or shown.spectrum
        x_lo, x_hi = self._spectrum_widget.get_x_view_range()
        return SpectrumRenderer().render_to_bytes(
            spectrum.wavenumbers,
            spectrum.intensities,
            shown.peaks,
            dpi=dpi or self._IMAGE_DPI,
            y_unit=spectrum.display_y_unit,
            is_dip_spectrum=spectrum.is_dip_spectrum,
            figsize=self._IMAGE_FIGSIZE,
            x_min=x_lo,
            x_max=x_hi,
            y_view_range=self._spectrum_widget.get_y_view_range(),
            split_at=2000.0 if ReportOptions().split_xaxis else None,
            label_placements=placements,
            image_format=image_format,
        )

    def _on_copy_spectrum_image(self) -> bool:
        """Edit → Copy Spectrum Image (Ctrl+Shift+C)."""
        from PySide6.QtGui import QImage  # noqa: PLC0415

        try:
            png = self._render_spectrum_image("png", dpi=200)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, tr("Copy Error"), tr("Failed to draw the spectrum:") + f"\n{exc}"
            )
            return False
        if png is None:
            self.statusBar().showMessage(tr("No spectrum loaded"))
            return False
        image = QImage.fromData(png)
        if image.isNull():
            return False
        QApplication.clipboard().setImage(image)
        self.statusBar().showMessage(tr("Spectrum image copied to the clipboard"))
        return True

    def _export_spectrum_image(self) -> bool:
        """Export the spectrum alone as a PNG (300 dpi) or an SVG (vector)."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage(tr("No spectrum loaded"))
            return False
        png_filter = tr("PNG image, 300 dpi (*.png)")
        svg_filter = tr("SVG vector image (*.svg)")
        path, chosen_filter = QFileDialog.getSaveFileName(
            self,
            tr("Export Spectrum Image"),
            self._suggested_save_path(".png"),
            f"{png_filter};;{svg_filter}",
        )
        if not path:
            return False
        suffix = Path(path).suffix.lower()
        if suffix not in (".png", ".svg"):
            is_svg = chosen_filter == svg_filter or "*.svg" in chosen_filter.lower()
            suffix = ".svg" if is_svg else ".png"
            path = f"{path}{suffix}"
        from file_io.atomic_output import atomic_output_path  # noqa: PLC0415

        try:
            data = self._render_spectrum_image(suffix.lstrip("."))
            if data is None:
                return False
            with atomic_output_path(Path(path)) as temp_path:
                temp_path.write_bytes(data)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("Export Error"), tr("Failed to export image:") + f"\n{e}")
            return False
        self._remember_save_dir(path)
        self.statusBar().showMessage(tr("Image exported: {name}").format(name=Path(path).name))
        return True

    def _on_ir_text_copied(self, text: str) -> None:
        if text:
            self.statusBar().showMessage(tr("IR text copied: {text}").format(text=text))
        else:
            self.statusBar().showMessage(tr("No peaks to write as IR text"))

    def _export_csv(
        self,
        *,
        include_unassigned: bool = False,
        mode: str = "combined",
        decimal_separator: str = ".",
    ) -> None:
        """Export peaks to a CSV file."""
        project = self._project
        if project is None or project.spectrum is None:
            self.statusBar().showMessage(tr("No spectrum loaded"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Export CSV"),
            self._suggested_save_path(".csv"),
            "CSV Files (*.csv);;Text Files (*.txt)",
        )
        if not path:
            return

        from pathlib import Path  # noqa: PLC0415

        from file_io.csv_exporter import CSVExporter  # noqa: PLC0415

        try:
            # What is exported is what is on screen: with the view switched to
            # another unit the numbers follow it, as the PDF report does.
            shown, _placements = self._project_as_displayed(project)
            spectrum = shown.corrected_spectrum or shown.spectrum
            CSVExporter().export(
                shown.peaks,
                Path(path),
                spectrum,
                include_unassigned=include_unassigned,
                project=shown,
                mode=mode,
                decimal_separator=decimal_separator,
            )
            self._remember_save_dir(path)
            self.statusBar().showMessage(tr("CSV exported: {name}").format(name=Path(path).name))
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("Export Error"), tr("Failed to export CSV:") + f"\n{e}")

    def _export_xlsx(
        self, *, include_unassigned: bool = False, include_chart: bool = False
    ) -> None:
        """Export peaks and spectrum to an Excel file."""
        project = self._project
        if project is None or project.spectrum is None:
            self.statusBar().showMessage(tr("No spectrum loaded"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Export Excel"),
            self._suggested_save_path(".xlsx"),
            "Excel Files (*.xlsx)",
        )
        if not path:
            return

        from pathlib import Path  # noqa: PLC0415

        from file_io.xlsx_exporter import XLSXExporter  # noqa: PLC0415

        try:
            shown, _placements = self._project_as_displayed(project)
            spectrum = shown.corrected_spectrum or shown.spectrum
            XLSXExporter().export(
                shown.peaks,
                Path(path),
                spectrum,
                include_unassigned=include_unassigned,
                project=shown,
                include_chart=include_chart,
            )
            self._remember_save_dir(path)
            self.statusBar().showMessage(tr("Excel exported: {name}").format(name=Path(path).name))
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("Export Error"), tr("Failed to export Excel:") + f"\n{e}")

    def _on_peak_selected(self, peak) -> None:
        """Update status bar and highlight matching presets when a peak is selected."""
        self.statusBar().showMessage(
            tr("Peak: {position} cm\u207b\u00b9  |  {intensity}").format(
                position=f"{peak.position:.2f}", intensity=f"{peak.intensity:.4f}"
            )
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
            tr('Removed "{name}" from peak at {position} cm\u207b\u00b9').format(
                name=preset.name, position=f"{peak.position:.1f}"
            )
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
                tr("Updated vibration text for {position} cm\u207b\u00b9").format(
                    position=f"{peak.position:.1f}"
                )
            )
        else:
            self.statusBar().showMessage(
                tr("Cleared vibration text for {position} cm\u207b\u00b9").format(
                    position=f"{peak.position:.1f}"
                )
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
        """Assign the highlighted preset to the currently selected peak.

        Reached from the panel's Assign button and Enter. A plain click in the
        list only outlines the vibration's range, so it can be browsed freely.
        """
        if self._project is None:
            return
        peak = self._peak_table.selected_peak()
        if peak is None:
            self.statusBar().showMessage(
                tr("Select a peak first, then double-click a vibration to assign it.")
            )
            return
        from core.commands import AssignPresetCommand  # noqa: PLC0415

        self._undo_stack.push(AssignPresetCommand(peak, preset))
        self._refresh_peak_views(peak)
        self.statusBar().showMessage(
            tr('Assigned "{name}" to peak at {position} cm\u207b\u00b9').format(
                name=preset.name, position=f"{peak.position:.1f}"
            )
        )

    def _on_peak_selected_in_viewer(self, peak) -> None:
        """Select peak in table and highlight presets when user clicks a peak in the chart."""
        self._spectrum_widget.set_selected_peak(peak)
        self._peak_table.select_peak(peak)
        self._vibration_panel.highlight_for_peak(peak.position)
        self._vibration_panel.set_active_peak(peak)
        self._set_functional_group_active_peak(peak)
        self.statusBar().showMessage(
            tr("Peak: {position} cm\u207b\u00b9  |  {intensity}").format(
                position=f"{peak.position:.2f}", intensity=f"{peak.intensity:.4f}"
            )
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
        self.statusBar().showMessage(tr("Peaks cleared"))

    def _on_arrange_peak_labels(self) -> None:
        """Auto-arrange peak labels without disturbing existing workflow until requested."""
        if self._project is None or not self._project.peaks:
            self.statusBar().showMessage(tr("No peaks available to arrange"))
            return

        placements = self._spectrum_widget.compute_auto_label_placements()
        if not placements:
            self.statusBar().showMessage(tr("No peak labels available to arrange"))
            return

        if all(
            abs(peak.label_offset_x - offset_x) <= 1e-6
            and abs(peak.label_offset_y - offset_y) <= 1e-6
            and peak.manual_placement
            for peak, offset_x, offset_y in placements
        ):
            self.statusBar().showMessage(tr("Peak labels are already arranged"))
            return

        from core.commands import SetPeakLabelPlacementsCommand  # noqa: PLC0415

        preferred_peak = self._peak_table.selected_peak()
        self._undo_stack.push(SetPeakLabelPlacementsCommand(placements))
        self._refresh_peak_views(preferred_peak)
        self._spectrum_widget.reset_view()
        self.statusBar().showMessage(tr("Peak labels arranged"))

    def _on_preset_selected(self, preset) -> None:
        """Assign the selected vibration preset to the currently active peak."""
        if self._project is None:
            return
        peak = self._peak_table.selected_peak()
        if peak is None:
            self.statusBar().showMessage(tr("Select a peak first, then double-click a preset."))
            return
        from core.commands import AssignPresetCommand  # noqa: PLC0415

        self._undo_stack.push(AssignPresetCommand(peak, preset))
        self._refresh_peak_views(peak)
        self.statusBar().showMessage(
            tr('Assigned "{name}" to peak at {position} cm\u207b\u00b9').format(
                name=preset.name, position=f"{peak.position:.1f}"
            )
        )

    def _on_vibration_preset_changed(self) -> None:
        """Reload vibration presets after one was added, edited, removed or reset.

        A renamed vibration is renamed on the peaks of the open project that
        carry it too, so the table, the plot and the report do not keep showing
        the old name.
        """
        old_names = {
            preset.db_id: preset.name
            for preset in self._vibration_presets_cache
            if preset.db_id is not None
        }
        self._reload_vibration_presets()
        renamed = {
            preset.db_id: (old_names[preset.db_id], preset.name)
            for preset in self._vibration_presets_cache
            if preset.db_id in old_names and old_names[preset.db_id] != preset.name
        }
        if renamed and self._apply_vibration_renames(renamed):
            self._mark_non_undo_dirty()
            self._refresh_peak_views(self._peak_table.selected_peak())

    def _apply_vibration_renames(self, renamed: dict) -> int:
        """Relabel peaks whose assignment points at a renamed vibration.

        A label is changed only when both its vibration id *and* its text match
        the vibration as it was. An id alone is not enough: assignments copied
        from a project made on another computer carry ids of that computer's
        library, which may name a different vibration here; and a label the
        analyst re-typed by hand is theirs to keep. Returns the number of
        labels changed.
        """
        if self._project is None:
            return 0
        changed = 0
        for peak in self._project.peaks:
            for index, preset_id in enumerate(peak.vibration_ids):
                if preset_id not in renamed or index >= len(peak.vibration_labels):
                    continue
                old_name, new_name = renamed[preset_id]
                if peak.vibration_labels[index] == old_name:
                    peak.vibration_labels[index] = new_name
                    changed += 1
        return changed

    def _on_structure_edited(self, smiles: str) -> None:
        """Handle SMILES change emitted by MoleculeWidget after dialog acceptance."""
        if self._project is None:
            return
        from core.commands import SetProjectSMILESCommand  # noqa: PLC0415

        mol_block = getattr(self._molecule_widget, "_current_mol_block", "") or ""
        self._undo_stack.push(SetProjectSMILESCommand(self._project, smiles, mol_block))
        self._update_dock_badges()
        self.statusBar().showMessage(tr("Proposed structure updated"))

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
        # Every highlighted row goes, as one undo step — deleting only the
        # "current" row of a multi-row selection left the rest behind.
        peaks = self._peak_table.selected_peaks()
        if not peaks:
            peak = self._peak_table.selected_peak()
            peaks = [peak] if peak is not None else []
        if not peaks:
            return
        from core.commands import DeletePeakCommand  # noqa: PLC0415

        if len(peaks) == 1:
            self._undo_stack.push(DeletePeakCommand(self._project, peaks[0]))
            message = tr("Deleted peak at {position} cm\u207b\u00b9").format(
                position=f"{peaks[0].position:.1f}"
            )
        else:
            self._undo_stack.beginMacro(f"Delete {len(peaks)} peaks")
            for peak in peaks:
                self._undo_stack.push(DeletePeakCommand(self._project, peak))
            self._undo_stack.endMacro()
            message = tr("Deleted {count} peaks").format(count=len(peaks))
        self._refresh_peak_views()
        self.statusBar().showMessage(message)

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
            self.statusBar().showMessage(tr("No spectrum loaded"))
            return

        if self._reference_search_thread is not None:
            self.statusBar().showMessage(tr("Reference search is already running"))
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
            QMessageBox.critical(self, tr("Match Error"), tr("Matching failed:") + f"\n{e}")
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
                tr("Matching result ignored because the project or filter changed.")
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
        self.statusBar().showMessage(tr("Matching failed"))
        QMessageBox.critical(self, tr("Match Error"), tr("Matching failed:") + f"\n{message}")

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
                    tr("Choose a reference library folder first in Database -> Reference Library.")
                )
            else:
                self.statusBar().showMessage(
                    tr("No reference spectra available. Sync or import the selected library first.")
                )
            self._clear_match_results()
            return

        self._current_match_results = list(outcome.results)
        self._refresh_saved_project_names()
        self._match_results_panel.set_results(list(outcome.results))
        self._dock_match.show()
        self._dock_match.raise_()
        self._refresh_consensus_analysis()
        if outcome.imported_summary is not None and outcome.imported_summary.imported > 0:
            self.statusBar().showMessage(
                tr("Imported {imported} references and matched against {count} spectra").format(
                    imported=outcome.imported_summary.imported, count=outcome.reference_count
                )
            )
        else:
            self.statusBar().showMessage(
                tr("Matched against {count} references").format(count=outcome.reference_count)
            )

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
            tr(
                "Saved projects are added to the reference library"
                if enabled
                else "Saved projects are no longer added to the reference library"
            )
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
            self.statusBar().showMessage(
                tr("Could not add to reference library: {error}").format(error=exc)
            )
            return None

    def _on_add_current_spectrum_to_library(self) -> None:
        """Database → Add Current Spectrum to Reference Library."""
        if self._project is None or self._project.spectrum is None:
            self.statusBar().showMessage(tr("No spectrum loaded"))
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
        self.statusBar().showMessage(
            tr("Annotated projects folder: {name}").format(name=Path(chosen).name)
        )

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
            QMessageBox.critical(
                self, tr("Apply Error"), f"Failed to read {project_path.name}:\n{exc}"
            )
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
            self.statusBar().showMessage(tr("Matching spectrum against reference library…"))

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
        self._fg_regions_checked = bool(visible)
        self._sync_functional_group_regions()

    def _on_functional_group_suggestion_selected(self, band) -> None:
        """Assign a suggested vibration to the selected peak via the existing command path."""
        if self._project is None:
            return
        peak = self._peak_table.selected_peak()
        if peak is None:
            self.statusBar().showMessage(tr("Select a peak first, then double-click a suggestion."))
            return
        if not band.covers_wavenumber(peak.position):
            self.statusBar().showMessage(
                tr("Selected peak is outside the suggested vibration range.")
            )
            return

        preset = self._find_best_preset_for_band(band, peak.position)
        if preset is None:
            self.statusBar().showMessage(
                tr("No matching vibration preset found for this suggestion.")
            )
            return

        from core.commands import AssignPresetCommand  # noqa: PLC0415

        preferred_group_id = self._current_functional_group_id()
        self._undo_stack.push(AssignPresetCommand(peak, preset))
        self._refresh_peak_views(peak)
        self._restore_functional_group_selection(preferred_group_id)
        self.statusBar().showMessage(
            tr('Assigned suggested vibration "{name}" to {position} cm\u207b\u00b9').format(
                name=preset.name, position=f"{peak.position:.1f}"
            )
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
        self._update_dock_badges()

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
            self.statusBar().showMessage(
                tr("Functional-group analysis unavailable: {error}").format(error=exc)
            )
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
            preset for preset in self._vibration_presets_cache if preset.answers_to(candidate_names)
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

        shown_spectrum = self._project.corrected_spectrum or self._project.spectrum
        self._peak_table.set_peaks(
            self._project.peaks,
            is_dip_spectrum=bool(shown_spectrum.is_dip_spectrum) if shown_spectrum else None,
        )
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
        self._update_status_chips()

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
            tr("Import Reference Spectrum"),
            "",
            "OMNIC SPA Files (*.spa *.SPA);;All Files (*)",
        )
        if not path:
            return

        from pathlib import Path  # noqa: PLC0415

        from app.reference_import import ReferenceImportService  # noqa: PLC0415

        try:
            imported = ReferenceImportService(self._db).import_reference_file(Path(path))
            self.statusBar().showMessage(
                tr("Reference imported: {name}").format(name=imported.name)
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self, tr("Import Error"), tr("Failed to import reference:") + f"\n{e}"
            )

    def _rebuild_recent_menu(self) -> None:
        """Rebuild the Open Recent submenu from settings."""
        if self._recent_menu is None:
            return
        self._recent_menu.clear()
        recent: list[str] = self._settings.get("recent_files") or []
        welcome = getattr(self, "_welcome", None)
        if welcome is not None:
            welcome.set_recent_files(list(recent) if isinstance(recent, list) else [])
        if not recent:
            no_action = self._recent_menu.addAction(tr("(empty)"))
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
        if self._closing_for_rebuild:
            event.accept()
            return
        # A headless/offscreen session has no user who could answer a modal
        # prompt. Interactive hidden windows still go through the data-loss guard.
        if not self.isVisible() and QApplication.platformName().casefold() == "offscreen":
            event.accept()
            return
        if self._reference_search_thread is not None:
            QMessageBox.information(
                self,
                tr("Operation in Progress"),
                tr(
                    "Reference matching is still running. Please wait for it to finish before closing."
                ),
            )
            event.ignore()
            return
        if self._confirm_project_replacement():
            self._save_window_layout()
            event.accept()
        else:
            event.ignore()

    # ── Welcome page and drag & drop ─────────────────────────────────────────

    def _setup_welcome(self) -> None:
        """Start page laid over the plot until a spectrum is loaded."""
        self._welcome = WelcomeOverlay(self._spectrum_widget)
        self._welcome.open_spectrum_requested.connect(self._on_open_file)
        self._welcome.open_project_requested.connect(self._on_open_project)
        self._welcome.recent_requested.connect(self._open_recent_path)
        self._spectrum_widget.installEventFilter(self)
        self._rebuild_recent_menu()
        self._update_welcome()

    def _update_welcome(self) -> None:
        """Show the start page only while the window has nothing loaded."""
        welcome = getattr(self, "_welcome", None)
        if welcome is None:
            return
        welcome.setGeometry(self._spectrum_widget.rect())
        welcome.setVisible(self._project is None)
        if self._project is None:
            welcome.raise_()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        """Keep the start page stretched over the plot area as it resizes."""
        if watched is getattr(self, "_spectrum_widget", None) and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            welcome = getattr(self, "_welcome", None)
            if welcome is not None:
                welcome.setGeometry(self._spectrum_widget.rect())
        return bool(super().eventFilter(watched, event))

    @classmethod
    def _droppable_paths(cls, mime_data) -> list[str]:
        """Local files in a drag that this window knows how to open."""
        if mime_data is None or not mime_data.hasUrls():
            return []
        paths = [url.toLocalFile() for url in mime_data.urls() if url.isLocalFile()]
        return [path for path in paths if path.lower().endswith(cls._OPENABLE_SUFFIXES)]

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._droppable_paths(event.mimeData()):
            self._welcome.set_drag_active(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._droppable_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._welcome.set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        """Open a dropped spectrum or project; further files go to the controller."""
        self._welcome.set_drag_active(False)
        paths = self._droppable_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self._remember_open_dir(paths[0])
        self._open_recent_path(paths[0])
        for extra in paths[1:]:
            self.open_path_requested.emit(extra)
