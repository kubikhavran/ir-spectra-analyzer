"""Shared lifecycle guard for dialogs that own a background ``QThread``."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


class BackgroundTaskDialogMixin:
    """Prevent a dialog from being destroyed while its worker thread is running."""

    _background_thread_attribute = ""

    def _background_task_is_running(self) -> bool:
        thread = getattr(self, self._background_thread_attribute, None)
        # Thread attributes are cleared only from QThread.finished handlers.
        # Treat the object as active until that cleanup slot runs, closing the
        # small gap between isRunning() becoming false and queued result/cleanup
        # signals reaching the dialog.
        return thread is not None

    def _show_background_task_running_message(self) -> None:
        QMessageBox.information(
            self,
            "Operation in progress",
            "Please wait for the current operation to finish before closing this window.",
        )

    def accept(self) -> None:
        if self._background_task_is_running():
            self._show_background_task_running_message()
            return
        # This is a cooperative mixin: every concrete user also inherits
        # QDialog, but that relationship cannot be expressed to mypy without
        # making QDialog a second base class here.
        super().accept()  # type: ignore[misc]

    def reject(self) -> None:
        if self._background_task_is_running():
            self._show_background_task_running_message()
            return
        super().reject()  # type: ignore[misc]

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._background_task_is_running():
            event.ignore()
            self._show_background_task_running_message()
            return
        super().closeEvent(event)  # type: ignore[misc]
