"""
This module contains the worker for processing statistics data.
"""

import logging
import os
from typing import List, Dict, Any
from PySide6.QtCore import QObject, Signal, QThread
from models.Profile import RollDirectory
from utils.profile_stats import Stats

log = logging.getLogger(__name__)


class StatisticsProcessorWorker(QObject):
    """
    A worker that processes all statistics for all rolls in a separate thread.

    Signals:
        progress(int, str, int): Emitted to report processing progress.
        finished(list, int): Emitted when complete with list of roll data.
        error(str, int): Emitted when an error occurs.
    """
    progress = Signal(int, str, int)
    finished = Signal(list, int)
    error = Signal(str, int)

    def __init__(self, root_directory: str, worker_id: int):
        super().__init__()
        self.root_directory = root_directory
        self.worker_id = worker_id
        self._running = True
        self.stats = Stats()

    def run(self):
        """
        Processes all statistics for all rolls at once.
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

            self.progress.emit(30, f"Processing {len(dir_paths_in_root_dir)} rolls...", self.worker_id)

            # Create RollDirectory objects
            roll_directories = [RollDirectory(d) for d in dir_paths_in_root_dir]

            if not self._running:
                return

            self.progress.emit(50, "Calculating all statistics...", self.worker_id)

            # Process all statistics for all rolls
            roll_data = self._process_all_rolls(roll_directories)

            if not self._running:
                return

            self.progress.emit(100, "Complete", self.worker_id)
            log.info(f"Statistics processing (worker {self.worker_id}) complete. Processed {len(roll_data)} rolls.")
            self.finished.emit(roll_data, self.worker_id)

        except Exception as e:
            log.error(f"Error during statistics processing (worker {self.worker_id}): {e}")
            if self._running:
                self.error.emit(str(e), self.worker_id)
            self.finished.emit([], self.worker_id)

    def _process_all_rolls(self, roll_directories: List[RollDirectory]) -> List[Dict[str, Any]]:
        """
        Calculate all statistics for all roll directories.
        Returns a list of roll data with all stats pre-computed.
        """
        roll_data = []
        total = len(roll_directories)

        # Get all stat functions
        stat_funcs = {
            'mean': self.stats.mean,
            'std': self.stats.std,
            'min': self.stats.min,
            'max': self.stats.max,
            'cv': self.stats.cv,
            'pp': self.stats.pp
        }

        for idx, roll_dir in enumerate(roll_directories):
            if not self._running:
                return roll_data

            # Update progress periodically
            if idx % max(1, total // 10) == 0:
                progress = 50 + int((idx / total) * 50)  # 50-100% range
                self.progress.emit(progress, f"Processing roll {idx + 1}/{total}...", self.worker_id)

            if roll_dir.mean_profile is not None and len(roll_dir.mean_profile) > 0:
                # Calculate all stats at once
                stats = {}
                for stat_name, stat_func in stat_funcs.items():
                    try:
                        stats[stat_name] = float(stat_func(roll_dir.mean_profile))
                    except Exception as e:
                        log.warning(f"Error calculating {stat_name} for {roll_dir.path}: {e}")
                        stats[stat_name] = None

                # Store roll data with all stats
                roll_data.append({
                    'label': os.path.basename(roll_dir.path),
                    'path': roll_dir.path,
                    'timestamp': roll_dir.newest_timestamp,
                    'stats': stats
                })

        # Sort by timestamp
        roll_data.sort(key=lambda r: r['timestamp'])
        return roll_data

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

    def start(self, root_directory: str):
        """
        Starts the statistics processing for all rolls and all stats.
        """
        # Stop any existing processing and wait for it to finish
        self.stop()

        # Assign a new worker ID
        self._current_worker_id = self._next_worker_id
        self._next_worker_id += 1

        self._thread = QThread()
        self._worker = StatisticsProcessorWorker(root_directory, self._current_worker_id)

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
