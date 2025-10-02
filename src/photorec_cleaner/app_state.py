"""
Provides the AppState class for sharing state across the application.
"""


class AppState:
    """A simple class to hold and share the application's state between modules."""

    def __init__(self):
        self.cleaned_folders = set()
        self.final_cleanup = False
        self.ready_for_final_cleanup = False
        self.total_deleted_size = 0
        self.total_deleted_count = 0
        self.total_kept_count = 0
        self.kept_files = {}
        self.log_writer = None
        self.current_activity = "Initializing..."
        self.app_state = "idle"
        self.spinner_index = 0
