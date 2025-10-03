"""
A Toga-based GUI for the PhotoRec Cleaner application.
"""
import csv
import asyncio
import datetime
import toga
from toga.style import Pack
from .file_utils import get_files_in_directory, clean_folder, organize_by_type, get_recup_dirs
from .app_state import AppState


def format_size(size_bytes):
    """Formats a size in bytes to a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes/1024**2:.1f} MB"
    else:
        return f"{size_bytes/1024**3:.1f} GB"


class PhotoRecCleanerApp(toga.App):  # pylint: disable=inherit-non-class
    def startup(self):
        """
        Construct and show the Toga application.
        """
        self.main_window = toga.MainWindow(title=self.formal_name)
        self.app_state = AppState()
        self.monitoring_task = None

        # Main box
        main_box = toga.Box(style=Pack(direction="column", margin=10))

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
        self.keep_ext_input = toga.TextInput(value="jpg,png,gif", style=Pack(flex=1))
        exclude_label = toga.Label(
            "Exclude (csv):", style=Pack(margin_left=10, margin_right=10)
        )
        self.exclude_ext_input = toga.TextInput(value="txt,xml", style=Pack(flex=1))

        ext_box.add(keep_label)
        ext_box.add(self.keep_ext_input)
        ext_box.add(exclude_label)
        ext_box.add(self.exclude_ext_input)
        main_box.add(ext_box)

        # Logging controls
        log_box = toga.Box(style=Pack(margin_bottom=10))
        self.log_switch = toga.Switch(
            "Enable Logging", on_change=self.toggle_log_path, style=Pack(margin_right=10)
        )
        self.log_path_input = toga.TextInput(readonly=True, style=Pack(flex=1))
        self.log_path_button = toga.Button(
            "Select Log Folder...",
            on_press=self.select_log_folder,
            style=Pack(margin_left=10),
        )
        self.toggle_log_path(self.log_switch)  # Set initial state

        log_box.add(self.log_switch)
        log_box.add(self.log_path_input)
        log_box.add(self.log_path_button)
        main_box.add(log_box)

        # Reorganization controls
        reorg_box = toga.Box(style=Pack(margin_bottom=10))
        self.reorg_switch = toga.Switch(
            "Reorganize Files", style=Pack(margin_right=10)
        )
        batch_label = toga.Label(
            "Batch Size:", style=Pack(margin_left=10, margin_right=10)
        )
        self.batch_size_input = toga.NumberInput(value=500, min=1, style=Pack(width=80))

        reorg_box.add(self.reorg_switch)
        reorg_box.add(batch_label)
        reorg_box.add(self.batch_size_input)
        main_box.add(reorg_box)

        # Running Tally
        tally_box = toga.Box(style=Pack(margin_top=10))
        self.folders_processed_label = toga.Label("Folders Processed: 0")
        self.files_kept_label = toga.Label("Files Kept: 0", style=Pack(margin_left=20))
        self.files_deleted_label = toga.Label(
            "Files Deleted: 0", style=Pack(margin_left=20)
        )
        self.space_saved_label = toga.Label(
            "Space Saved: 0 B", style=Pack(margin_left=20)
        )
        tally_box.add(self.folders_processed_label)
        tally_box.add(self.files_kept_label)
        tally_box.add(self.files_deleted_label)
        tally_box.add(self.space_saved_label)
        main_box.add(tally_box)

        # Action buttons
        action_box = toga.Box(style=Pack(margin_top=10))
        self.start_button = toga.Button(
            "Start Monitoring", on_press=self.start_monitoring_handler
        )
        self.finish_button = toga.Button(
            "Finish", on_press=self.finish_handler, enabled=False
        )
        action_box.add(self.start_button)
        action_box.add(self.finish_button)
        main_box.add(action_box)

        # Status label
        self.status_label = toga.Label("Ready", style=Pack(margin_top=10))
        main_box.add(self.status_label)

        self.main_window.content = main_box
        self.main_window.show()

    def toggle_log_path(self, widget):
        self.log_path_input.enabled = widget.value
        self.log_path_button.enabled = widget.value

    async def select_log_folder(self, widget):
        try:
            path = await self.main_window.dialog(
                toga.SelectFolderDialog("Select Log Folder", initial_directory=None)
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
        except ValueError:
            await self.main_window.dialog(
                toga.InfoDialog("Cancelled", "Directory selection was cancelled.")
            )

    def start_monitoring_handler(self, widget):
        if not self.dir_path_input.value:
            asyncio.create_task(
                self.main_window.dialog(
                    toga.InfoDialog("Error", "Please select a directory to monitor first.")
                )
            )
            return

        self.start_button.enabled = False
        self.finish_button.enabled = True
        # Start async monitoring task
        self.monitoring_task = asyncio.create_task(self.start_monitoring_task())

    async def start_monitoring_task(self):
        base_dir = self.dir_path_input.value
        keep_ext = {ext.strip() for ext in self.keep_ext_input.value.split(",") if ext.strip()}
        exclude_ext = {ext.strip() for ext in self.exclude_ext_input.value.split(",") if ext.strip()}
        processed_folders = set()

        log_file = None
        try:
            if self.log_switch.value:
                log_folder = self.log_path_input.value
                if not log_folder:
                    await self.main_window.dialog(
                        toga.InfoDialog("Error", "Please select a log folder.")
                    )
                    self.finish_handler(None)
                    return

                timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                log_path = f"{log_folder}/photorec_cleaner_{timestamp}.csv"

                log_file = open(log_path, "w", newline="")
                self.app_state.log_writer = csv.writer(log_file)
                self.app_state.log_writer.writerow(
                    ["Folder", "File Name", "Extension", "Status", "Size"]
                )

            while True:
                recup_dirs = get_recup_dirs(base_dir)
                if recup_dirs:
                    active_folder = recup_dirs[-1]
                    folders_to_process = [
                        d
                        for d in recup_dirs
                        if d not in processed_folders and d != active_folder
                    ]

                    for folder in folders_to_process:
                        self.status_label.text = f"Processing {folder}..."
                        clean_folder(
                            folder,
                            self.app_state,
                            keep_ext=keep_ext,
                            exclude_ext=exclude_ext,
                            logger=self.update_status,
                        )
                        processed_folders.add(folder)
                        self.app_state.cleaned_folders.add(folder)
                        self.update_tally()

                self.status_label.text = "Monitoring..."
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            self.status_label.text = "Monitoring stopped."
        finally:
            if log_file:
                log_file.close()

    def update_status(self, message):
        self.status_label.text = message

    def update_tally(self):
        self.folders_processed_label.text = (
            f"Folders Processed: {len(self.app_state.cleaned_folders)}"
        )
        self.files_kept_label.text = f"Files Kept: {self.app_state.total_kept_count}"
        self.files_deleted_label.text = (
            f"Files Deleted: {self.app_state.total_deleted_count}"
        )
        self.space_saved_label.text = (
            f"Space Saved: {format_size(self.app_state.total_deleted_size)}"
        )

    def finish_handler(self, widget):
        if self.monitoring_task:
            self.monitoring_task.cancel()
            self.monitoring_task = None

        base_dir = self.dir_path_input.value
        if not base_dir:
            return

        recup_dirs = get_recup_dirs(base_dir)
        if recup_dirs:
            last_folder = recup_dirs[-1]
            if last_folder not in self.app_state.cleaned_folders:
                self.status_label.text = f"Processing final folder {last_folder}..."
                keep_ext = {
                    ext.strip() for ext in self.keep_ext_input.value.split(",") if ext.strip()
                }
                exclude_ext = {
                    ext.strip() for ext in self.exclude_ext_input.value.split(",") if ext.strip()
                }
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

        # Final Report
        report = (
            f"Photorec Cleaning Complete\n\n"
            f"Folders Processed: {len(self.app_state.cleaned_folders)}\n"
            f"Files Kept: {self.app_state.total_kept_count}\n"
            f"Files Deleted: {self.app_state.total_deleted_count}\n"
            f"Total Space Saved: {format_size(self.app_state.total_deleted_size)}"
        )
        asyncio.create_task(
            self.main_window.dialog(toga.InfoDialog("Final Report", report))
        )

        self.start_button.enabled = True
        self.finish_button.enabled = False


def main():
    return PhotoRecCleanerApp("PhotoRec Cleaner", "org.beeware.photorec_cleaner")


if __name__ == "__main__":
    main().main_loop()
