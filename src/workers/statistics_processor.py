"""
This module contains the worker for processing statistics data.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any
from PySide6.QtCore import QObject, Signal, QThread
from models.Profile import RollDirectory
from utils.profile_stats import Stats

log = logging.getLogger(__name__)


class StatisticsProcessorWorker(QObject):
    """
    A worker that processes statistics data in a separate thread.

    Signals:
        progress(int, str, int): Emitted to report processing progress. The first
            argument is the percentage (0-100), the second is a
            status message, and the third is the worker ID.
        finished(list, int): Emitted when the processing is complete. The first argument
            is a list of stat data dictionaries, the second is the worker ID.
        error(str, int): Emitted when an error occurs during processing. The first
            argument is the error message, the second is the worker ID.
    """
    progress = Signal(int, str, int)
    finished = Signal(list, int)
    error = Signal(str, int)

    def __init__(self, root_directory: str, selected_stat: str, filter_option: str, worker_id: int):
        super().__init__()
        self.root_directory = root_directory
        self.selected_stat = selected_stat
        self.filter_option = filter_option
        self.worker_id = worker_id
        self._running = True
        self.stats = Stats()

    def run(self):
        """
        Starts the statistics processing.
        """
        if not self._running:
            return

        try:
            log.info(f"Starting statistics processing (worker {self.worker_id}) for {self.root_directory}")
            self.progress.emit(10, "Loading directories...", self.worker_id)

            # Load directories
            paths_in_root_dir = [
                os.path.join(self.root_directory, d)
                for d in os.listdir(self.root_directory)
            ]
            dir_paths_in_root_dir = [d for d in paths_in_root_dir if os.path.isdir(d)]

            if not self._running:
                return

            self.progress.emit(30, f"Processing {len(dir_paths_in_root_dir)} directories...", self.worker_id)

            # Create RollDirectory objects
            roll_directories = [RollDirectory(d) for d in dir_paths_in_root_dir]

            if not self._running:
                return

            self.progress.emit(60, "Calculating statistics...", self.worker_id)

            # Process statistics
            stat_data = self._get_roll_stat_data(roll_directories)

            if not self._running:
                return

            self.progress.emit(100, "Complete", self.worker_id)
            log.info(f"Statistics processing (worker {self.worker_id}) complete. Generated {len(stat_data)} data points.")
            self.finished.emit(stat_data, self.worker_id)

        except Exception as e:
            log.error(f"Error during statistics processing (worker {self.worker_id}): {e}")
            if self._running:
                self.error.emit(str(e), self.worker_id)
            self.finished.emit([], self.worker_id)

    def _get_roll_stat_data(self, roll_directories: List[RollDirectory]) -> List[Dict[str, Any]]:
        """
        Calculate statistics for roll directories with filtering.
        """
        points = []
        stat_key = self.selected_stat.lower()

        try:
            stat_func = getattr(self.stats, stat_key)
        except AttributeError:
            log.error(f"Unknown stat: {self.selected_stat}")
            return []

        # Get current time for filtering
        now = datetime.now()

        total = len(roll_directories)
        for idx, roll_dir in enumerate(roll_directories):
            if not self._running:
                return points

            # Update progress periodically
            if idx % max(1, total // 10) == 0:
                progress = 60 + int((idx / total) * 30)  # 60-90% range
                self.progress.emit(progress, f"Processing roll {idx + 1}/{total}...", self.worker_id)

            if roll_dir.mean_profile is not None and len(roll_dir.mean_profile) > 0:
                # Apply time filter
                roll_time = datetime.fromtimestamp(roll_dir.newest_timestamp)

                # Check if roll should be included based on filter
                include_roll = True

                if self.filter_option == "FILTER_LAST_7_DAYS":
                    if roll_time < (now - timedelta(days=7)):
                        include_roll = False
                elif self.filter_option == "FILTER_LAST_30_DAYS":
                    if roll_time < (now - timedelta(days=30)):
                        include_roll = False

                if include_roll:
                    y = stat_func(roll_dir.mean_profile)
                    x = roll_dir.newest_timestamp
                    label = os.path.basename(roll_dir.path)
                    points.append({'x': x, 'y': y, 'label': label, 'path': roll_dir.path})

        points.sort(key=lambda p: p['x'])
        return points

    def stop(self):
        """
        Stops the processing.
        """
        self._running = False
        log.info("Stopping statistics processor.")


class StatisticsProcessor(QObject):
    """
    Manages the statistics processing in a separate thread.
    """

    progress = Signal(int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None
        self._is_running = False
        self._current_worker_id = 0
        self._next_worker_id = 1

    def start(self, root_directory: str, selected_stat: str, filter_option: str):
        """
        Starts the statistics processing.
        """
        # Stop any existing processing and wait for it to finish
        self.stop()

        # Assign a new worker ID
        self._current_worker_id = self._next_worker_id
        self._next_worker_id += 1

        self._thread = QThread()
        self._worker = StatisticsProcessorWorker(root_directory, selected_stat, filter_option, self._current_worker_id)

        self._worker.moveToThread(self._thread)

        # Connect signals
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.started.connect(self._worker.run)

        log.info(f"Starting statistics processor thread (worker {self._current_worker_id}).")
        self._is_running = True
        self._thread.start()

    def _on_progress(self, value: int, status_text: str, worker_id: int):
        """Internal handler for progress signal."""
        # Only emit progress if this is the current worker
        if worker_id == self._current_worker_id:
            self.progress.emit(value, status_text)

    def _on_finished(self, result, worker_id: int):
        """Internal handler for finished signal."""
        # Only emit if this is still the active worker (not replaced)
        if worker_id == self._current_worker_id and self._is_running:
            self._is_running = False
            self.finished.emit(result)

    def _on_error(self, error_message: str, worker_id: int):
        """Internal handler for error signal."""
        # Only emit if this is the current worker
        if worker_id == self._current_worker_id:
            self.error.emit(error_message)

    def _on_thread_finished(self):
        """Internal handler for thread cleanup."""
        # Don't clean up references here - let stop() handle it
        # This prevents race conditions when rapidly starting/stopping
        log.debug("Thread finished executing.")

    def stop(self):
        """
        Stops the processing if it's running.
        """
        if not self._is_running:
            return

        self._is_running = False

        # Save references to current thread/worker
        thread = self._thread
        worker = self._worker

        # Clear references immediately to prevent new signals from being processed
        self._thread = None
        self._worker = None

        # Stop the worker if it exists
        if worker:
            try:
                worker.stop()
            except RuntimeError:
                # Worker already deleted
                pass

        # Wait for thread to finish if it's running
        if thread is not None:
            try:
                if thread.isRunning():
                    log.info("Stopping statistics processor thread.")
                    thread.quit()
                    # Wait with timeout to prevent indefinite blocking
                    if not thread.wait(5000):  # 5 second timeout
                        log.warning("Thread did not stop within timeout, forcing termination.")
                        thread.terminate()
                        thread.wait()
            except RuntimeError:
                # Thread object already deleted
                pass

    def is_running(self):
        return self._is_running
