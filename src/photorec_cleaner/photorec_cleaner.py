"""
Main script for the PhotoRec Cleaner application.

This script orchestrates the process of monitoring PhotoRec's output directories,
cleaning unwanted files based on user-defined rules, and optionally
reorganizing the kept files into a structured format. It provides a
console-based user interface to show real-time progress.
"""

import os
import time
import argparse
import csv

from . import console_ui as ui
from . import file_utils as fu
from .app_state import AppState


def _setup_logging(base_dir, state):
    """Initializes the CSV logger if enabled."""
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = f"photorec_cleaner_log_{timestamp}.csv"
    log_filepath = os.path.join(base_dir, log_filename)
    try:
        log_file = open(log_filepath, "w", newline="", encoding="utf-8")
        state.log_writer = csv.writer(log_file)
        state.log_writer.writerow(
            ["Folder", "Filename", "Type", "Status", "Size (Bytes)"]
        )
        print(f"  Logging actions to: {ui.GREEN}{log_filepath}{ui.RESET}")
        return log_file
    except OSError as e:
        print(f"{ui.RED}Error creating log file: {e}{ui.RESET}")
        state.log_writer = None
        return None


def _monitor_and_clean_dirs(state, base_dir, keep_ext, exclude_ext, interval):
    """The main loop to monitor and clean recup_dir folders as they appear."""
    while not state.final_cleanup:
        try:
            dirs = fu.get_recup_dirs(base_dir)
            num_dirs = len(dirs)

            if num_dirs == 0:
                state.app_state = "idle"
                state.current_activity = (
                    "Waiting for PhotoRec to create the first folder..."
                )
            elif num_dirs == 1:
                state.app_state = "monitoring"
                state.current_activity = f"Monitoring {os.path.basename(dirs[0])}..."
            else:  # num_dirs > 1
                # Clean all but the last directory, which is currently being written to
                state.app_state = "cleaning"
                for folder in dirs[:-1]:
                    if folder not in state.cleaned_folders:
                        fu.clean_folder(folder, state, keep_ext, exclude_ext)
                        state.cleaned_folders.add(folder)

            time.sleep(interval)

        except KeyboardInterrupt:
            print("\nExiting without final cleanup.")
            state.final_cleanup = True  # Exit the loop cleanly
            return False  # Indicate that we should not proceed to final cleanup

    return True  # Indicate normal completion


def _perform_final_cleanup(state, base_dir, keep_ext, exclude_ext):
    """Cleans all remaining folders after the monitoring loop."""
    state.app_state = "cleaning"
    state.current_activity = "Performing final cleanup..."
    for folder in fu.get_recup_dirs(base_dir):
        if folder not in state.cleaned_folders:
            fu.clean_folder(folder, state, keep_ext, exclude_ext)
            state.cleaned_folders.add(folder)


def _print_final_summary(state, reorganize, log_enabled):
    """Prints a clean summary of all operations at the end of the script."""
    print("\n" + "=" * (ui.BOX_WIDTH + 2))
    print(f"{f'{ui.BOLD}PhotoRec Cleaner Finished{ui.RESET}':^{ui.BOX_WIDTH + 10}}")
    print("=" * (ui.BOX_WIDTH + 2))

    if reorganize:
        print("  - Files reorganized into type-based folders.")
    if log_enabled:
        print("  - Actions logged to CSV file.")

    print("\n" + f"{ui.BOLD}Summary:{ui.RESET}")
    print(f"  - Total files kept     : {state.total_kept_count}")
    print(f"  - Total files deleted  : {state.total_deleted_count}")
    print(f"  - Total space freed    : {ui.format_size(state.total_deleted_size)}")
    print("\n" + "=" * (ui.BOX_WIDTH + 2) + "\n")


def run_cleaner(
    base_dir, keep_ext, exclude_ext, interval, batch_size, reorganize, log_enabled
):
    """
    Orchestrates the entire cleaning and organizing process.

    Args:
        base_dir (str): The root directory of the PhotoRec output.
        keep_ext (set): A set of file extensions to keep.
        exclude_ext (set): A set of file extensions to delete.
        interval (int): The time in seconds between checking for new folders.
        batch_size (int): The number of files to put in each subfolder during reorganization.
        reorganize (bool): Whether to reorganize kept files into typed folders.
        log_enabled (bool): Whether to create a CSV log of file operations.
    """
    state = AppState()
    ui.print_intro(base_dir)

    # Create initial space for the UI to draw into, after the intro
    print("\n" * ui.BOX_HEIGHT)

    log_file = _setup_logging(base_dir, state) if log_enabled else None

    watcher_thread, _ = ui.start_ui_threads(state)

    # The main monitoring loop. It returns False if interrupted.
    _monitor_and_clean_dirs(state, base_dir, keep_ext, exclude_ext, interval)

    # Wait for the user to confirm completion via the input_watcher thread
    while not state.ready_for_final_cleanup:
        if not watcher_thread.is_alive():  # Handle Ctrl+C during monitoring
            if log_file:
                log_file.close()
            return
        time.sleep(0.1)

    # Final cleanup after user input
    _perform_final_cleanup(state, base_dir, keep_ext, exclude_ext)

    ui.clear_screen()
    if reorganize:
        fu.organize_by_type(base_dir, state, batch_size=batch_size)

    if log_file:
        log_file.close()

    _print_final_summary(state, reorganize, log_enabled)


def main():
    """Parses command-line arguments and starts the cleaner."""
    description = (
        "PhotoRec folder cleaner: remove unwanted recovered files and optionally "
        "organize by type."
    )
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Path to the PhotoRec output directory.",
    )
    parser.add_argument(
        "-k",
        "--keep",
        nargs="+",
        help="Defines an allow list. Only files with these extensions will be kept; all others are deleted.",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        nargs="+",
        help="Defines a deny list. Files with these extensions will be deleted. This rule overrides --keep if both are used.",
    )

    parser.add_argument(
        "-t",
        "--interval",
        type=int,
        default=5,
        help="Seconds between scanning for new folders. (default: 5)",
    )

    parser.add_argument(
        "-b",
        "--batch-size",
        type=int,
        default=500,
        help="Max number of files per subfolder when reorganizing. (default: 500)",
    )

    parser.add_argument(
        "-r",
        "--reorganize",
        action="store_true",
        help=(
            "After cleaning, move kept files into folders named by file type "
            "and remove the old `recup_dir.X` folders."
        ),
    )

    parser.add_argument(
        "-l",
        "--log",
        action="store_true",
        help="Log all file actions (kept/deleted) to a timestamped CSV file in the output directory.",
    )

    args = parser.parse_args()

    if not args.keep and not args.exclude:
        parser.error("At least one of -k/--keep or -x/--exclude must be specified.")

    # Convert extensions to lowercase for case-insensitive matching
    keep_ext = {ext.lower() for ext in args.keep} if args.keep else None
    exclude_ext = {ext.lower() for ext in args.exclude} if args.exclude else None

    run_cleaner(
        args.input,
        keep_ext,
        exclude_ext,
        args.interval,
        args.batch_size,
        args.reorganize,
        args.log,
    )


if __name__ == "__main__":
    main()
