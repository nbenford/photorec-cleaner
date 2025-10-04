"""
Cleaner core logic. Exposes a Cleaner class with a run_once() method
that performs one pass of scanning/cleaning. This keeps the long-running
work out of the event loop; gui.py will call run_once via asyncio.to_thread.


This module deliberately keeps side effects minimal: it returns structured
results rather than mutating UI objects directly.
"""

import os
import time
from typing import Dict, Iterable, Optional, Tuple

from .app_state import AppState
from .file_utils import clean_folder, get_recup_dirs


class Cleaner:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir

    def _normalize_ext_set(self, ext_csv: str) -> set:
        return {e.strip().lower() for e in ext_csv.split(",") if e.strip()}

    def run_once(
        self,
        keep_ext_csv: str,
        exclude_ext_csv: str,
        app_state: AppState,
        logger: Optional[callable] = None,
    ) -> Dict:
        """Perform a single scan/clean pass.


        Returns a dict with keys:
        - processed_folders: list of processed folder paths
        - last_deleted: last deleted filepath (or None)
        - cleaned_count: number of folders cleaned this pass
        - timestamp: time.time() at end
        """
        keep_ext = self._normalize_ext_set(keep_ext_csv)
        exclude_ext = self._normalize_ext_set(exclude_ext_csv)

        # Clear kept_files for this pass to avoid re-counting from previous passes.
        app_state.kept_files.clear()

        processed = []
        last_deleted = None

        recup_dirs = get_recup_dirs(self.base_dir)
        if not recup_dirs:
            return {
                "processed_folders": [],
                "last_deleted": None,
                "cleaned_count": 0,
                "timestamp": time.time(),
            }

        active_folder = recup_dirs[-1]
        folders_to_process = [
            d
            for d in recup_dirs
            if d not in app_state.cleaned_folders and d != active_folder
        ]

        for folder in folders_to_process:
            # clean_folder is expected to update app_state via the app_state passed in
            # and optionally call logger(message)
            clean_folder(
                folder,
                app_state,
                keep_ext=keep_ext,
                exclude_ext=exclude_ext,
                logger=logger,
            )
            app_state.cleaned_folders.add(folder)
            processed.append(folder)

        # We can't reliably know the last deleted file path unless clean_folder reports it via logger.
        # For compatibility, we don't invent that here; the logger callback (from GUI) should capture
        # the most recent filename reported.
        return {
            "processed_folders": processed,
            "last_deleted": None,
            "cleaned_count": len(processed),
            "timestamp": time.time(),
        }
