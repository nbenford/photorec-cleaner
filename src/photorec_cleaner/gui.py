"""
Toga GUI for PhotoRec Cleaner — rewritten to run the cleaning logic
off-thread, keep the UI responsive, avoid dangling tasks, and provide
concise status updates.

Notes:
 - Uses asyncio.create_task to start the monitor loop.
 - Calls Cleaner.run_once inside asyncio.to_thread to avoid blocking the event loop.
 - Provides two status labels: one for general state and one for the last file (truncated).
 - Graceful shutdown: Finish button cancels the background task and waits briefly for it to stop.
"""

import asyncio
import csv
import os
from typing import Optional

import toga
from toga.style import Pack
from toga.constants import BLUE, GREEN, RED

from .app_state import AppState
from .file_utils import clean_folder, get_recup_dirs, organize_by_type
from .photorec_cleaner import Cleaner

MAX_STATUS_PATH = 80


def shorten_path(path: str, maxlen: int = MAX_STATUS_PATH) -> str:
    if not path:
        return ""
    if len(path) <= maxlen:
        return path
    # keep start and end bits for readability
    head = path[: maxlen // 2 - 2]
    tail = path[-(maxlen // 2 - 1) :]
    return f"{head}...{tail}"


class PhotoRecCleanerApp(toga.App):
    def startup(self):
        self.main_window = toga.MainWindow(title=self.formal_name)
        self.app_state = AppState()
        self.monitoring_task: Optional[asyncio.Task] = None
        self._stop_monitoring = False
        self.cleaner: Optional[Cleaner] = None
        self._last_deleted_name: Optional[str] = None

        self.build_ui()
        self.main_window.content = self.main_box
        self.main_window.on_close = (
            self.on_close
        )  # ensure graceful shutdown on window close
        self.main_window.show()

    def build_ui(self):
        main_box = toga.Box(style=Pack(direction="column", margin=10, flex=1))

        # Directory selection
        dir_box = toga.Box(style=Pack(margin_bottom=10))
        dir_label = toga.Label("Directory to Monitor:", style=Pack(margin_right=10))
        self.dir_path_input = toga.TextInput(readonly=True, style=Pack(flex=1))
        dir_select_button = toga.Button(
            "Select...", on_press=self.select_directory, style=Pack(margin_left=10)
        )
        dir_box.add(dir_label)
        dir_box.add(self.dir_path_input)
        dir_box.add(dir_select_button)
        main_box.add(dir_box)

        # Extension inputs
        ext_box = toga.Box(style=Pack(margin_bottom=10))
        keep_label = toga.Label("Keep (csv):", style=Pack(margin_right=10))
        self.keep_ext_input = toga.TextInput(value="gz,sqlite", style=Pack(flex=1))
        exclude_label = toga.Label(
            "Exclude (csv):", style=Pack(margin_left=10, margin_right=10)
        )
        self.exclude_ext_input = toga.TextInput(value="html.gz,xml.gz", style=Pack(flex=1))
        ext_box.add(keep_label)
        ext_box.add(self.keep_ext_input)
        ext_box.add(exclude_label)
        ext_box.add(self.exclude_ext_input)
        main_box.add(ext_box)

        # Logging controls
        log_box = toga.Box(style=Pack(margin_bottom=10))
        self.log_switch = toga.Switch(
            "Enable Logging",
            on_change=self.toggle_log_path,
            style=Pack(margin_right=10),
        )
        self.log_path_input = toga.TextInput(readonly=True, style=Pack(flex=1))
        self.log_path_button = toga.Button(
            "Select Log Folder...",
            on_press=self.select_log_folder,
            style=Pack(margin_left=10),
        )
        self.toggle_log_path(self.log_switch)
        log_box.add(self.log_switch)
        log_box.add(self.log_path_input)
        log_box.add(self.log_path_button)
        main_box.add(log_box)

        # Reorganization controls
        reorg_box = toga.Box(style=Pack(margin_bottom=10))
        self.reorg_switch = toga.Switch("Reorganize Files", style=Pack(margin_right=10))
        batch_label = toga.Label(
            "Batch Size:", style=Pack(margin_left=10, margin_right=10)
        )
        self.batch_size_input = toga.NumberInput(value=500, min=1, style=Pack(width=80))
        reorg_box.add(self.reorg_switch)
        reorg_box.add(batch_label)
        reorg_box.add(self.batch_size_input)
        main_box.add(reorg_box)
        main_box.add(toga.Divider(margin_top=10, margin_bottom=10))

        # Running Tally
        tally_box = toga.Box(style=Pack(margin_top=10, margin=5))
        self.folders_processed_label = toga.Label("Folders Processed: 0", font_weight="bold", font_size=10, flex=1)
        self.files_kept_label = toga.Label("Files Kept: 0", style=Pack(margin_left=20),font_weight="bold", font_size=10, flex=1)
        self.files_deleted_label = toga.Label(
            "Files Deleted: 0", style=Pack(margin_left=20,font_weight="bold", font_size=10, flex=1)
        )
        self.space_saved_label = toga.Label(
            "Space Saved: 0 B", style=Pack(margin_left=20,font_weight="bold", font_size=10, flex=1)
        )
        tally_box.add(self.folders_processed_label)
        tally_box.add(self.files_kept_label)
        tally_box.add(self.files_deleted_label)
        tally_box.add(self.space_saved_label)
        
        
        main_box.add(tally_box)
        main_box.add(toga.Divider(margin_top=20, margin_bottom=10))

        # Status area (two labels)
        status_box = toga.Box(style=Pack(direction="column", margin=7), flex=2)
        self.status_label = toga.Label("Ready",font_family="monospace", font_size=10, color=GREEN, font_weight="bold")
        self.last_deleted_label = toga.Label("")
        status_box.add(self.status_label)
        status_box.add(self.last_deleted_label)

        scroll_container = toga.ScrollContainer(content=status_box, horizontal=False, vertical=True)

        main_box.add(scroll_container)
        main_box.add(toga.Divider(margin_top=10, margin_bottom=10))

        # Action buttons
        action_box = toga.Box(style=Pack(margin_top=10, flex=1, align_items="end", margin_bottom=10))
        self.clean_now_button = toga.Button(
            "Clean Now", on_press=self.clean_now_handler, enabled=False, flex=1, margin=5, font_weight="bold", font_size=10, height=30
        )
        self.start_button = toga.Button(
            "Start Monitoring", on_press=self.start_monitoring_handler, flex=1, margin=5, font_weight="bold", font_size=10, height=30
        )
        self.finish_button = toga.Button(
            "Finish", on_press=self.finish_handler, enabled=False, flex=1, margin=5, font_weight="bold", font_size=10, height=30
        )
        action_box.add(self.clean_now_button)
        action_box.add(self.start_button)
        action_box.add(self.finish_button)
        main_box.add(action_box)

        self.main_box = main_box

    def toggle_log_path(self, widget):
        self.log_path_input.enabled = widget.value
        self.log_path_button.enabled = widget.value

    async def select_log_folder(self, widget):
        try:
            path = await self.main_window.dialog(
                toga.SelectFolderDialog(
                    title="Select Log Folder", initial_directory=None
                )
            )
            if path:
                self.log_path_input.value = str(path)
        except ValueError:
            await self.main_window.dialog(
                toga.InfoDialog("Cancelled", "Log folder selection was cancelled.")
            )

    async def select_directory(self, widget):
        try:
            path = await self.main_window.dialog(
                toga.SelectFolderDialog(
                    title="Select Directory to Monitor", initial_directory=None
                )
            )
            if path:
                self.dir_path_input.value = str(path)
                self.log_path_input.value = str(path)
                # instantiate Cleaner for the selected directory
                self.cleaner = Cleaner(str(path))

                # Check for existing recup_dirs to enable the "Clean Now" button
                recup_dirs = get_recup_dirs(str(path))
                self.clean_now_button.enabled = bool(recup_dirs)

        except ValueError:
            await self.main_window.dialog(
                toga.InfoDialog("Cancelled", "Directory selection was cancelled.")
            )
        self.app_state.reset()
        self.update_tally()

    def start_monitoring_handler(self, widget):
        if not self.dir_path_input.value:
            # show error dialog without blocking
            asyncio.create_task(
                self.main_window.dialog(
                    toga.InfoDialog(
                        "Error", "Please select a directory to monitor first."
                    )
                )
            )
            return

        if self.monitoring_task and not self.monitoring_task.done():
            return  # already running

        self._stop_monitoring = False
        self.clean_now_button.enabled = False
        self.start_button.enabled = False
        self.finish_button.enabled = True
        # start the monitor loop

        # Handle log file creation
        if self.log_switch.value and self.log_path_input.value:
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_filename = f"photorec_cleaner_log_{ts}.csv"
            log_filepath = os.path.join(self.log_path_input.value, log_filename)
            try:
                # The file handle needs to be kept open.
                self.app_state.log_file_handle = open(log_filepath, "w", newline="")
                self.app_state.log_writer = csv.writer(self.app_state.log_file_handle)
                self.app_state.log_writer.writerow(["Folder", "Filename", "Extension", "Status", "Size"])
            except OSError as e:
                self.status_label.text = f"Error creating log file: {e}"

        self.monitoring_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self):
        # run single-pass cleaner repeatedly but off the event loop
        try:
            while not self._stop_monitoring:
                if not self.cleaner:
                    self.status_label.text = "No directory selected"
                    await asyncio.sleep(1)
                    continue

                self.status_label.text = "Scanning..."

                # run the cleaner's run_once in a thread to avoid blocking
                try:
                    result = await asyncio.to_thread(
                        self.cleaner.run_once,
                        self.keep_ext_input.value,
                        self.exclude_ext_input.value,
                        self.app_state,
                        self._logger_callback,
                    )
                except Exception as e:
                    # log but do not crash the loop
                    self.status_label.text = f"Cleaner error: {e}"
                    await asyncio.sleep(2)
                    continue

                # update UI after the run_once pass
                if result.get("cleaned_count", 0) > 0:
                    self.status_label.text = (
                        f"Processed {result['cleaned_count']} folders"
                    )
                else:
                    self.status_label.text = "Monitoring..."

                # update tally labels
                self.update_tally()

                # keep the UI responsive and limit how often we run
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            # handle cancellation gracefully
            self.status_label.text = "Monitoring stopped."
        finally:
            # ensure state is consistent
            self.monitoring_task = None

    def _logger_callback(self, message: str):
        # This callback is called from clean_folder (running in a thread). Keep it cheap.
        # We expect messages like: "Deleted: /path/to/file" or status strings.
        # Record the last deleted filename for the UI, but avoid heavy UI work here.
        if not message:
            return
        lower = message.lower()
        # detect deleted file mention — heuristic depends on your clean_folder logger
        if "deleted" in lower or "moved" in lower:
            # attempt to extract a filename from the message
            parts = message.split()
            # take last token as filename candidate
            candidate = parts[-1]
            # schedule UI update on the event loop
            self._last_deleted_name = candidate
            try:
                asyncio.get_event_loop().call_soon_threadsafe(
                    self._update_last_deleted_label
                )
            except Exception:
                # in some environments the event loop may differ; ignore failures here
                pass
        else:
            # generic status message
            try:
                asyncio.get_event_loop().call_soon_threadsafe(
                    self._set_status_text_threadsafe, message
                )
            except Exception:
                pass

    def _update_last_deleted_label(self):
        text = f"Last deleted: {shorten_path(self._last_deleted_name or '')}"
        self.last_deleted_label.text = text

    def _set_status_text_threadsafe(self, message: str):
        # Keep status concise to avoid layout thrashing
        self.status_label.text = shorten_path(message, maxlen=120)

    def update_tally(self):
        self.folders_processed_label.text = (
            f"Folders Processed: {len(self.app_state.cleaned_folders)}"
        )
        self.files_kept_label.text = f"Files Kept: {self.app_state.total_kept_count}"
        self.files_deleted_label.text = (
            f"Files Deleted: {self.app_state.total_deleted_count}"
        )
        self.space_saved_label.text = (
            f"Space Saved: {self._format_size(self.app_state.total_deleted_size)}"
        )

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024**2:
            return f"{size_bytes / 1024:.1f} KB"
        if size_bytes < 1024**3:
            return f"{size_bytes / 1024**2:.1f} MB"
        return f"{size_bytes / 1024**3:.1f} GB"

    def finish_handler(self, widget):
        # Stop the monitor loop and perform final processing on the main thread.
        if not self.monitoring_task:
            return

        # signal the loop to stop
        self._stop_monitoring = True
        # cancel the task; it will exit promptly
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()

        # perform final synchronous cleanup (process final folder + optional reorg)
        base_dir = self.dir_path_input.value
        if not base_dir:
            self.start_button.enabled = True
            self.finish_button.enabled = False
            return

        recup_dirs = get_recup_dirs(base_dir)
        if recup_dirs:
            last_folder = recup_dirs[-1]
            if last_folder not in self.app_state.cleaned_folders:
                self.status_label.text = (
                    f"Processing final folder {shorten_path(last_folder, 60)}..."
                )
                keep_ext = {
                    ext.strip()
                    for ext in self.keep_ext_input.value.split(",")
                    if ext.strip()
                }
                exclude_ext = {
                    ext.strip()
                    for ext in self.exclude_ext_input.value.split(",")
                    if ext.strip()
                }
                # run the final pass synchronously to ensure deterministic completion
                clean_folder(
                    last_folder,
                    self.app_state,
                    keep_ext=keep_ext,
                    exclude_ext=exclude_ext,
                    logger=self.update_status,
                )
                self.app_state.cleaned_folders.add(last_folder)
                self.update_tally()

        if self.reorg_switch.value:
            self.status_label.text = "Reorganizing files..."
            batch_size = int(self.batch_size_input.value)
            organize_by_type(base_dir, self.app_state, batch_size=batch_size)
            self.status_label.text = "Reorganization complete."

        # show final report
        report = (
            f"Photorec Cleaning Complete\n\n"
            f"Folders Processed: {len(self.app_state.cleaned_folders)}\n"
            f"Files Kept: {self.app_state.total_kept_count}\n"
            f"Files Deleted: {self.app_state.total_deleted_count}\n"
            f"Total Space Saved: {self._format_size(self.app_state.total_deleted_size)}"
        )
        asyncio.create_task(
            self.main_window.dialog(toga.InfoDialog("Final Report", report))
        )

        # Close the log file if it was opened
        if getattr(self.app_state, "log_file_handle", None):
            self.app_state.log_file_handle.close()
            self.app_state.log_writer = None

        # Re-check for existing folders to set button state correctly
        recup_dirs = get_recup_dirs(base_dir)
        self.clean_now_button.enabled = bool(recup_dirs)
        self.start_button.enabled = True
        self.finish_button.enabled = False

    async def clean_now_handler(self, widget):
        """Handler for the 'Clean Now' button to process existing folders."""
        base_dir = self.dir_path_input.value
        if not base_dir:
            return

        # Disable buttons during processing
        self.clean_now_button.enabled = False
        self.start_button.enabled = False

        # Get the loop from the main thread before switching to a background thread.
        loop = asyncio.get_running_loop()
        # Run the potentially long-running task in a thread
        await asyncio.to_thread(self._perform_one_shot_clean, base_dir, loop)

        # Re-enable start button, but keep clean_now disabled as folders are gone
        self.start_button.enabled = True

    def _perform_one_shot_clean(self, base_dir: str, loop: asyncio.AbstractEventLoop):
        """Synchronous method to clean all existing folders."""
        self.app_state.reset()
        asyncio.run_coroutine_threadsafe(self._update_tally_async(), loop)

        # Handle log file creation for one-shot clean
        if self.log_switch.value and self.log_path_input.value:
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_filename = f"photorec_cleaner_log_{ts}.csv"
            log_filepath = os.path.join(self.log_path_input.value, log_filename)
            try:
                # The file handle needs to be kept open.
                self.app_state.log_file_handle = open(log_filepath, "w", newline="")
                self.app_state.log_writer = csv.writer(self.app_state.log_file_handle)
                self.app_state.log_writer.writerow(["Folder", "Filename", "Extension", "Status", "Size"])
            except OSError as e:
                message = f"Error creating log file: {e}"
                asyncio.run_coroutine_threadsafe(self._set_status_text_async(message), loop)

        recup_dirs = get_recup_dirs(base_dir)
        if not recup_dirs:
            message = "No 'recup_dir' folders found to clean."
            asyncio.run_coroutine_threadsafe(self._set_status_text_async(message), loop)
            return

        keep_ext = {
            ext.strip() for ext in self.keep_ext_input.value.split(",") if ext.strip()
        }
        exclude_ext = {
            ext.strip()
            for ext in self.exclude_ext_input.value.split(",")
            if ext.strip()
        }

        for i, folder in enumerate(recup_dirs):
            message = f"Processing folder {i + 1}/{len(recup_dirs)}..."
            asyncio.run_coroutine_threadsafe(self._set_status_text_async(message), loop)
            clean_folder(
                folder,
                self.app_state,
                keep_ext=keep_ext,
                exclude_ext=exclude_ext,
                logger=self._logger_callback,
            )
            self.app_state.cleaned_folders.add(folder)
            asyncio.run_coroutine_threadsafe(self._update_tally_async(), loop)

        if self.reorg_switch.value:
            message = "Reorganizing files..."
            asyncio.run_coroutine_threadsafe(self._set_status_text_async(message), loop)
            batch_size = int(self.batch_size_input.value)
            organize_by_type(base_dir, self.app_state, batch_size=batch_size)
            message = "Reorganization complete."
            asyncio.run_coroutine_threadsafe(self._set_status_text_async(message), loop)

        # Show final report in a thread-safe way
        report = (
            f"One-Shot Cleaning Complete\n\n"
            f"Folders Processed: {len(self.app_state.cleaned_folders)}\n"
            f"Files Kept: {self.app_state.total_kept_count}\n"
            f"Files Deleted: {self.app_state.total_deleted_count}\n"
            f"Total Space Saved: {self._format_size(self.app_state.total_deleted_size)}"
        )
        asyncio.run_coroutine_threadsafe(
            self._show_dialog_async("One-Shot Cleaning Complete", report),
            loop,
        )

        # Close the log file if it was opened
        if getattr(self.app_state, "log_file_handle", None):
            self.app_state.log_file_handle.close()
            self.app_state.log_writer = None
            self.app_state.log_file_handle = None


    def update_status(self, message: str):
        # called from file_utils cleaners which might run in the main thread
        self.status_label.text = shorten_path(message, maxlen=120)

    async def _update_tally_async(self):
        """Async version of update_tally to be called from other threads."""
        self.update_tally()

    async def _set_status_text_async(self, message: str):
        """Async version of setting status text to be called from other threads."""
        self.status_label.text = shorten_path(message, maxlen=120)

    async def _show_dialog_async(self, title: str, message: str):
        """Creates and shows a dialog from a coroutine, ensuring it's on the main thread."""
        dialog = toga.InfoDialog(title, message)
        await self.main_window.dialog(dialog)

    def on_close(self, widget=None, **kwargs):
        # ensure monitoring stops when window closes
        self._stop_monitoring = True
        if self.monitoring_task and not self.monitoring_task.done():
            try:
                self.monitoring_task.cancel()
            except Exception:
                pass
        # allow the app to close; do not block the UI loop here
        return True


def main():
    return PhotoRecCleanerApp("PhotoRec Cleaner", "org.beeware.photorec_cleaner")


if __name__ == "__main__":
    main().main_loop()
