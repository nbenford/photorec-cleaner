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

import toga
from toga.style import Pack
from toga.constants import GREEN

from ..photorec_cleaner.app_state import AppState
from ..photorec_cleaner.file_utils import get_recup_dirs
from .controller import AppController
from .gui_utils import shorten_path


class PhotoRecCleanerApp(toga.App):
    def startup(self):
        self.main_window = toga.MainWindow(title=self.formal_name)
        self.app_state = AppState()
        self.controller = AppController(self, self.app_state)

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
        dir_label = toga.Label(
            "PhotoRec Output Directory:", style=Pack(margin_right=10)
        )
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
        self.cleaning_switch = toga.Switch(
            "Enable File Deletion",
            on_change=self.toggle_cleaning_controls,
            style=Pack(margin_right=10),
        )
        keep_label = toga.Label("Keep (csv):", style=Pack(margin_right=10))
        self.keep_ext_input = toga.TextInput(value="gz,sqlite", style=Pack(flex=1))
        exclude_label = toga.Label(
            "Exclude (csv):", style=Pack(margin_left=10, margin_right=10)
        )
        self.exclude_ext_input = toga.TextInput(
            value="html.gz,xml.gz", style=Pack(flex=1)
        )
        ext_box.add(self.cleaning_switch)
        ext_box.add(keep_label)
        ext_box.add(self.keep_ext_input)
        ext_box.add(exclude_label)
        ext_box.add(self.exclude_ext_input)

        self._set_initial_cleaning_controls_state()

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
        tally_box = toga.Box(style=Pack(margin_top=10))
        self.folders_processed_label = toga.Label(
            "Folders Processed: 0", font_weight="bold", font_size=10, flex=1
        )
        self.files_kept_label = toga.Label(
            "Files Kept: 0",
            style=Pack(margin_left=20),
            font_weight="bold",
            font_size=10,
            flex=1,
        )
        self.files_deleted_label = toga.Label(
            "Files Deleted: 0",
            style=Pack(margin_left=20, font_weight="bold", font_size=10, flex=1),
        )
        self.space_saved_label = toga.Label(
            "Space Saved: 0 B",
            style=Pack(
                margin_left=20,
                font_weight="bold",
                font_size=10,
                flex=1,
                margin_right=20,
            ),
        )
        tally_box.add(self.folders_processed_label)
        tally_box.add(self.files_kept_label)
        tally_box.add(self.files_deleted_label)
        tally_box.add(self.space_saved_label)

        main_box.add(tally_box)
        main_box.add(toga.Divider(margin_top=20, margin_bottom=10))

        # Guidance message area
        self.guidance_label = toga.Label(
            "", style=Pack(text_align="center", font_style="italic", margin_bottom=5)
        )
        main_box.add(self.guidance_label)

        # Status area (one label)
        status_box = toga.Box(style=Pack(direction="column", margin=7), flex=2)
        self.status_label = toga.Label(
            "Ready",
            font_family="monospace",
            font_size=10,
            color=GREEN,
            font_weight="bold",
        )

        status_box.add(self.status_label)

        scroll_container = toga.ScrollContainer(
            content=status_box, horizontal=False, vertical=True
        )

        main_box.add(scroll_container)
        main_box.add(toga.Divider(margin_top=10, margin_bottom=10))

        # Action buttons
        action_box = toga.Box(
            style=Pack(margin_top=10, flex=1, align_items="end", margin_bottom=10)
        )
        self.clean_now_button = toga.Button(
            "Process Now",
            on_press=self.clean_now_handler,
            enabled=False,
            flex=1,
            margin=5,
            font_weight="bold",
            font_size=10,
            height=30,
        )
        self.start_button = toga.Button(
            "Start Live Monitoring",
            on_press=self.start_monitoring_handler,
            enabled=False,
            flex=1,
            margin=5,
            font_weight="bold",
            font_size=10,
            height=30,
        )
        self.finish_button = toga.Button(
            "Finalize",
            on_press=self.finish_handler,
            enabled=False,
            flex=1,
            margin=5,
            font_weight="bold",
            font_size=10,
            height=30,
        )
        action_box.add(self.clean_now_button)
        action_box.add(self.start_button)
        action_box.add(self.finish_button)
        main_box.add(action_box)

        self.main_box = main_box

    def _set_initial_cleaning_controls_state(self):
        """Sets the initial enabled state of the cleaning controls."""
        self.keep_ext_input.enabled = self.cleaning_switch.value
        self.exclude_ext_input.enabled = self.cleaning_switch.value

    async def toggle_cleaning_controls(self, widget):
        if widget.value:
            confirmed = await self.main_window.dialog(
                toga.ConfirmDialog(
                    "Confirm Permanent Deletion",
                    "Are you sure you want to enable file deletion? This action is permanent and cannot be undone.",
                )
            )
            if not confirmed:
                widget.value = False

        self.keep_ext_input.enabled = widget.value
        self.exclude_ext_input.enabled = widget.value

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
                    title="Select PhotoRec Output Directory", initial_directory=None
                )
            )
            if path:
                self.dir_path_input.value = str(path)
                self.log_path_input.value = str(path)
                self.controller.set_cleaner(str(path))
                self.controller.start_folder_polling()
                self.start_button.enabled = True

        except ValueError:
            await self.main_window.dialog(
                toga.InfoDialog("Cancelled", "Directory selection was cancelled.")
            )
        self.app_state.reset()
        self.update_tally()

    def start_monitoring_handler(self, widget):
        self.clean_now_button.enabled = False
        self.start_button.enabled = False
        self.finish_button.enabled = True
        self.guidance_label.text = (
            "Live monitoring started. Click 'Finalize' when PhotoRec is finished."
        )
        self.status_label.text = "Monitoring..."  # Set initial status immediately
        self.controller.start_monitoring()

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
        self.controller.finish_processing()

        # Show final report
        self._show_final_report()

        base_dir = self.dir_path_input.value
        recup_dirs = get_recup_dirs(base_dir)
        self.clean_now_button.enabled = bool(recup_dirs)
        self.start_button.enabled = True
        self.finish_button.enabled = False
        self.app_state.reset()
        self.guidance_label.text = ""
        self.update_tally()

    async def clean_now_handler(self, widget):
        """Handler for the 'Clean Now' button to process existing folders."""
        # Disable buttons during processing
        self.clean_now_button.enabled = False
        self.start_button.enabled = False

        await self.controller.perform_one_shot_clean()

        # Re-enable start button, but keep clean_now disabled as folders are gone
        self.start_button.enabled = True
        self.app_state.reset()
        self.guidance_label.text = ""
        self.update_tally()

    def _show_final_report(self):
        report_title = "Processing Complete"
        report_body = (
            f"Photorec Cleaning Complete\n\n"
            f"Folders Processed: {len(self.app_state.cleaned_folders)}\n"
            f"Files Kept: {self.app_state.total_kept_count}\n"
            f"Files Deleted: {self.app_state.total_deleted_count}\n"
            f"Total Space Saved: {self._format_size(self.app_state.total_deleted_size)}"
        )
        asyncio.run_coroutine_threadsafe(
            self._show_dialog_async(report_title, report_body),
            asyncio.get_running_loop(),
        )

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
        self.controller.on_close()
        return True


def main():
    return PhotoRecCleanerApp(
        "PhotoRec Cleaner",
        "org.beeware.photorec_cleaner",
        icon="resources/photorec_cleaner",
    )


if __name__ == "__main__":
    main().main_loop()
