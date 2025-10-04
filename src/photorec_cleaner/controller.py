"""
Controller for the PhotoRec Cleaner GUI.

This class encapsulates the application logic, separating it from the Toga
UI implementation in `gui.py`. It handles user actions, manages background
tasks, and updates the application state.
"""

import asyncio
import csv
import os
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from ..photorec_cleaner.app_state import AppState
from ..photorec_cleaner.file_utils import clean_folder, get_recup_dirs, organize_by_type
from ..photorec_cleaner.photorec_cleaner import Cleaner
from .gui_utils import shorten_path

if TYPE_CHECKING:
    from .gui import PhotoRecCleanerApp


class AppController:
    """Handles application logic for the PhotoRecCleanerApp."""

    def __init__(self, app: "PhotoRecCleanerApp", app_state: AppState):
        self.app = app
        self.app_state = app_state
        self.loop = asyncio.get_running_loop()
        self.cleaner: Optional[Cleaner] = None
        self.monitoring_task: Optional[asyncio.Task] = None
        self.polling_task: Optional[asyncio.Task] = None
        self._stop_monitoring = False

    def set_cleaner(self, path: str):
        """Instantiates the Cleaner for a given directory."""
        self.cleaner = Cleaner(path)

    def start_folder_polling(self):
        """Starts a background task to poll for new folders."""
        if self.polling_task and not self.polling_task.done():
            self.polling_task.cancel()

        self.polling_task = asyncio.create_task(self._poll_for_folders())

    async def _poll_for_folders(self):
        """Periodically checks for recup_dir folders to enable the Process Now button."""
        base_dir = self.app.dir_path_input.value
        if not base_dir:
            return

        while True:
            # Only poll if monitoring is NOT active
            if not self.monitoring_task or self.monitoring_task.done():
                recup_dirs = await asyncio.to_thread(get_recup_dirs, base_dir)
                self.app.clean_now_button.enabled = bool(recup_dirs)
            await asyncio.sleep(2)  # Poll every 2 seconds

    def start_monitoring(self):
        """Starts the background monitoring task."""
        if self.monitoring_task and not self.monitoring_task.done():
            return  # Already running

        self._stop_monitoring = False
        # Stop the folder poller if it's running, as monitoring takes over.
        if self.polling_task and not self.polling_task.done():
            self.polling_task.cancel()

        self._setup_logging()
        self.monitoring_task = asyncio.create_task(self._monitor_loop())

    def _setup_logging(self):
        """Creates and opens the log file if logging is enabled."""
        if self.app.log_switch.value and self.app.log_path_input.value:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_filename = f"photorec_cleaner_log_{ts}.csv"
            log_filepath = os.path.join(self.app.log_path_input.value, log_filename)
            try:
                # The file handle needs to be kept open.
                self.app_state.log_file_handle = open(log_filepath, "w", newline="")
                self.app_state.log_writer = csv.writer(self.app_state.log_file_handle)
                self.app_state.log_writer.writerow(
                    ["Folder", "Filename", "Extension", "Status", "Size"]
                )
            except OSError as e:
                self.app.status_label.text = f"Error creating log file: {e}"

    async def _monitor_loop(self):
        """The core loop for repeated scanning and cleaning."""
        try:
            while not self._stop_monitoring:
                if not self.cleaner:
                    self.app.status_label.text = "No directory selected"
                    await asyncio.sleep(1)
                    continue

                # Check for folders. If none, set status and wait.
                recup_dirs = await asyncio.to_thread(
                    get_recup_dirs, self.cleaner.base_dir
                )
                if not recup_dirs:
                    self.app.status_label.text = "Monitoring..."
                    self.app.update_tally()
                    await asyncio.sleep(1)
                    continue

                if self.app.status_label.text == "Monitoring...":
                    self.app.status_label.text = "Processing..."

                # Pass empty strings for extensions if cleaning is disabled
                keep_csv = (
                    self.app.keep_ext_input.value
                    if self.app.cleaning_switch.value
                    else ""
                )
                exclude_csv = (
                    self.app.exclude_ext_input.value
                    if self.app.cleaning_switch.value
                    else ""
                )

                # run_once will now handle both processing completed folders and
                # scanning the active one. The logger callbacks within it are the
                # source of truth for the status label.
                await asyncio.to_thread(
                    self.cleaner.run_once,
                    keep_csv,
                    exclude_csv,
                    self.app_state,
                    self._logger_callback,
                )

                self.app.update_tally()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            self.app.status_label.text = "Monitoring stopped."
        finally:
            self.monitoring_task = None
            self.start_folder_polling()  # Restart polling when monitoring stops

    def finish_processing(self):
        """Stops monitoring and performs final cleanup and reorganization."""
        if self.monitoring_task and not self.monitoring_task.done():
            self._stop_monitoring = True
            self.monitoring_task.cancel()

        base_dir = self.app.dir_path_input.value
        if not base_dir:
            return

        recup_dirs = get_recup_dirs(base_dir)
        if recup_dirs:
            last_folder = recup_dirs[-1]
            if last_folder not in self.app_state.cleaned_folders:
                self.app.status_label.text = (
                    f"Processing final folder {shorten_path(last_folder, 60)}..."
                )
                # Respect the cleaning switch for the final pass
                keep_ext_str = (
                    self.app.keep_ext_input.value
                    if self.app.cleaning_switch.value
                    else ""
                )
                exclude_ext_str = (
                    self.app.exclude_ext_input.value
                    if self.app.cleaning_switch.value
                    else ""
                )
                keep_ext = {
                    ext.strip() for ext in keep_ext_str.split(",") if ext.strip()
                }
                exclude_ext = {
                    ext.strip() for ext in exclude_ext_str.split(",") if ext.strip()
                }
                clean_folder(
                    last_folder,
                    self.app_state,
                    keep_ext=keep_ext,
                    exclude_ext=exclude_ext,
                    logger=self.app.update_status,
                )
                self.app_state.cleaned_folders.add(last_folder)
                self.app.update_tally()

        if self.app.reorg_switch.value:
            self.app.status_label.text = "Reorganizing files..."
            batch_size = int(self.app.batch_size_input.value)
            organize_by_type(base_dir, self.app_state, batch_size=batch_size)
            self.app.status_label.text = "Reorganization complete."

        self._close_log_file()

    def _close_log_file(self):
        """Closes the log file handle if it's open."""
        if getattr(self.app_state, "log_file_handle", None):
            self.app_state.log_file_handle.close()
            self.app_state.log_writer = None
            self.app_state.log_file_handle = None

    async def perform_one_shot_clean(self):
        """Runs the cleaning process once for all existing folders."""
        base_dir = self.app.dir_path_input.value
        if not base_dir:
            return

        loop = asyncio.get_running_loop()
        await asyncio.to_thread(self._one_shot_clean_sync, base_dir, loop)

    def _one_shot_clean_sync(self, base_dir: str, loop: asyncio.AbstractEventLoop):
        """Synchronous method to clean all existing folders."""
        self.app_state.reset()
        asyncio.run_coroutine_threadsafe(self.app._update_tally_async(), loop)

        self._setup_logging()

        recup_dirs = get_recup_dirs(base_dir)
        if not recup_dirs:
            message = "No 'recup_dir' folders found to clean."
            asyncio.run_coroutine_threadsafe(
                self.app._set_status_text_async(message), loop
            )
            return

        # Respect the cleaning switch for the one-shot process
        keep_ext_str = (
            self.app.keep_ext_input.value if self.app.cleaning_switch.value else ""
        )
        exclude_ext_str = (
            self.app.exclude_ext_input.value if self.app.cleaning_switch.value else ""
        )
        keep_ext = {ext.strip() for ext in keep_ext_str.split(",") if ext.strip()}
        exclude_ext = {ext.strip() for ext in exclude_ext_str.split(",") if ext.strip()}

        for i, folder in enumerate(recup_dirs):
            message = f"Processing folder {i + 1}/{len(recup_dirs)}..."
            asyncio.run_coroutine_threadsafe(
                self.app._set_status_text_async(message), loop
            )
            clean_folder(
                folder,
                self.app_state,
                keep_ext=keep_ext,
                exclude_ext=exclude_ext,
                logger=self._logger_callback,
                prefix="Processing",
            )
            self.app_state.cleaned_folders.add(folder)
            asyncio.run_coroutine_threadsafe(self.app._update_tally_async(), loop)

        if self.app.reorg_switch.value:
            message = "Reorganizing files..."
            asyncio.run_coroutine_threadsafe(
                self.app._set_status_text_async(message), loop
            )
            batch_size = int(self.app.batch_size_input.value)
            organize_by_type(base_dir, self.app_state, batch_size=batch_size)
            message = "Reorganization complete."
            asyncio.run_coroutine_threadsafe(
                self.app._set_status_text_async(message), loop
            )

        report = (
            f"One-Shot Processing Complete\n\n"
            f"Folders Processed: {len(self.app_state.cleaned_folders)}\n"
            f"Files Kept: {self.app_state.total_kept_count}\n"
            f"Files Deleted: {self.app_state.total_deleted_count}\n"
            f"Total Space Saved: {self.app._format_size(self.app_state.total_deleted_size)}"
        )
        asyncio.run_coroutine_threadsafe(
            self.app._show_dialog_async("Processing Complete", report),
            loop,
        )

        self._close_log_file()

    def on_close(self):
        """Handles app shutdown."""
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()
        
        if self.polling_task and not self.polling_task.done():
            self.polling_task.cancel()
            
        self._close_log_file()

    def _logger_callback(self, message: str):
        """Callback from background threads to update UI with status."""
        if not message:
            return

        # Pass all messages to the status label
        self.loop.call_soon_threadsafe(self.app.update_status, message)
