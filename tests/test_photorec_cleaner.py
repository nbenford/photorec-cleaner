import unittest
from unittest.mock import patch, MagicMock

from src.photorec_cleaner.photorec_cleaner import Cleaner
from src.photorec_cleaner.app_state import AppState

class TestCleaner(unittest.TestCase):

    def setUp(self):
        self.app_state = AppState()
        self.base_dir = "/fake/base/dir"
        self.cleaner = Cleaner(self.base_dir)

    @patch('src.photorec_cleaner.photorec_cleaner.get_recup_dirs')
    def test_run_once_no_recup_dirs(self, mock_get_recup_dirs):
        """
        Test that run_once returns early and does nothing if no recup_dirs are found.
        """
        mock_get_recup_dirs.return_value = []

        result = self.cleaner.run_once("", "", self.app_state)

        self.assertEqual(len(result["processed_folders"]), 0)
        self.assertEqual(result["cleaned_count"], 0)
        mock_get_recup_dirs.assert_called_once_with(self.base_dir)

    @patch('src.photorec_cleaner.photorec_cleaner.clean_folder')
    @patch('src.photorec_cleaner.photorec_cleaner.get_recup_dirs')
    def test_run_once_with_multiple_folders(self, mock_get_recup_dirs, mock_clean_folder):
        """
        Test the core logic of run_once with a mix of cleaned, uncleaned, and active folders.
        """
        # --- Arrange ---
        dir1, dir2, dir3 = "/fake/d1", "/fake/d2", "/fake/d3"
        mock_get_recup_dirs.return_value = [dir1, dir2, dir3]
        self.app_state.cleaned_folders.add(dir1)  # Simulate that dir1 is already cleaned

        mock_logger = MagicMock()

        # --- Act ---
        result = self.cleaner.run_once("jpg", "", self.app_state, logger=mock_logger)

        # --- Assert ---
        # Verify that clean_folder was called only for the uncleaned, non-active folder
        mock_clean_folder.assert_called_once()
        self.assertEqual(mock_clean_folder.call_args[0][0], dir2)

        # Verify logger calls
        self.assertIn(f"Processing {dir2}", [call[0][0] for call in mock_logger.call_args_list])
        self.assertIn(
            f"Processing folder: d3",
            [call[0][0] for call in mock_logger.call_args_list],
        )

        # Verify result and app_state
        self.assertEqual(result["processed_folders"], [dir2])
        self.assertIn(dir2, self.app_state.cleaned_folders)
        self.assertEqual(result["cleaned_count"], 1)

