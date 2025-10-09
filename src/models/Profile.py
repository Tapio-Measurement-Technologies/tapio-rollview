from dataclasses import dataclass, field
from numpy.typing import NDArray
import numpy as np
import struct
from PySide6.QtCore import (
    QAbstractTableModel,
    Qt,
    QModelIndex,
    QDateTime
)
import os
from typing import List
from utils.profile_stats import calc_mean_profile
from utils.file_utils import list_prof_files
import settings

PROF_FILE_HEADER_SIZE = 128


@dataclass(frozen=True)
class ProfileData:
    distances: NDArray
    hardnesses: NDArray

    @classmethod
    def frombytes(cls, data: bytes, sample_step):
        hardnesses = []
        offset = 0

        # Read hardness values until we run out of data
        while offset + 4 <= len(data):
            chunk = data[offset:offset+4]
            hardness = struct.unpack('f', chunk)[0]
            hardnesses.append(hardness)
            offset += 4

        if settings.FLIP_DATA:
            hardnesses = hardnesses[::-1]

        # Generate distances if we have valid sample step and hardness data
        if sample_step > 0 and len(hardnesses) > 0:
            # Calculate the total distance traveled
            current_distance = sample_step * len(hardnesses)
            # Create a distance array from 0 to current_distance in steps of sample_step
            distances = np.arange(0, current_distance, sample_step)[
                :len(hardnesses)]
            return cls(distances=distances, hardnesses=hardnesses)
        else:
            print("Invalid sample step or no hardness values in data.")
            return None

    @property
    def x(self):
        return self.distances

    @property
    def y(self):
        return self.hardnesses


@dataclass(frozen=True)
class ProfileHeader:
    prof_version: int   # File format version
    serial_number: str  # Measurement device serial number
    sample_step: float  # Sample step in millimeters

    @classmethod
    def frombytes(cls, data: bytes):
        # Ensure the data is at least long enough to contain the expected header fields
        if len(data) != PROF_FILE_HEADER_SIZE:
            print(
                f"Invalid header size (actual {len(data)} != expected {PROF_FILE_HEADER_SIZE})")
            return None

        try:
            # prof_version: 4 bytes (int)
            prof_version = int.from_bytes(
                data[0:4], byteorder='little', signed=False)
            # serial_number: 32 bytes (string, null-terminated)
            serial_number = data[4:36].decode(
                'ISO-8859-1', errors='replace').split('\x00', 1)[0]
            # sample_step: 4 bytes (float)
            sample_step = struct.unpack('f', data[36:40])[0]

            return cls(
                prof_version=prof_version, serial_number=serial_number, sample_step=sample_step
            )

        except Exception as e:
            print(f"Failed to parse header from data: {e}")
            return None

    @classmethod
    def fromfile(cls, file_path):
        with open(file_path, 'rb') as file:
            header_data = file.read(128)
            profile_header = cls.parse(header_data)
            return profile_header


@dataclass
class Profile:
    path: str
    data: ProfileData | None
    header: ProfileHeader
    file_size: int
    date_modified: float
    hidden: bool = False

    @classmethod
    def fromfile(cls, file_path):
        file_stats = os.stat(file_path)
        file_size = file_stats.st_size
        date_modified_timestamp = file_stats.st_mtime

        with open(file_path, 'rb') as file:
            header_data = file.read(128)
            header = ProfileHeader.frombytes(header_data)
            if not header:
                return None
            sample_step = header.sample_step / 1000.0   # mm -> m
            profile_data = file.read()
            data = ProfileData.frombytes(profile_data, sample_step)

        return cls(
            path=file_path,
            data=data,
            header=header,
            file_size=file_size,
            date_modified=date_modified_timestamp
        )

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def profile_length(self):
        if self.data is None or len(self.data.distances) == 0:
            return 0
        return self.data.distances[-1]


@dataclass
class RollDirectory:
    path: str
    profiles: List['Profile'] = field(default_factory=list, init=False)
    mean_profile: NDArray | None = field(default=None, init=False)

    def __post_init__(self):
        self.update()

    def update(self):
        prof_paths = list_prof_files(self.path)
        self.profiles = [Profile.fromfile(path) for path in prof_paths]
        self.distances, self.mean_profile = calc_mean_profile(self.profiles)

    @property
    def newest_timestamp(self):
        if len(self.profiles) > 0:
            return max(p.date_modified for p in self.profiles)
        else:
            return os.path.getmtime(self.path)

# Not used at the moment but might be useful in the future


class ProfileModel(QAbstractTableModel):
    COLUMNS = ["", "Name", "File Size", "Date Modified", "Profile Length"]

    def __init__(self, profiles: List['Profile'], parent=None):
        super().__init__(parent)
        self._profiles = profiles

    def rowCount(self, parent=QModelIndex()):
        return len(self._profiles)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        profile = self._profiles[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                # For display, just return an empty string since the checkbox will be shown anyway
                return ""
            elif col == 1:
                return profile.name
            elif col == 2:
                return f"{profile.file_size} bytes"
            elif col == 3:
                dt = QDateTime.fromSecsSinceEpoch(int(profile.date_modified))
                return dt.toString(Qt.DateFormat.ISODate)
            elif col == 4:
                return f"{profile.profile_length:.3f} m"

        # For the checkbox state
        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            return Qt.CheckState.Checked if profile.hidden else Qt.CheckState.Unchecked

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None

        if orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section]

        return super().headerData(section, orientation, role)

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        if index.column() == 0:
            # Hidden column is checkable
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
        else:
            # Other columns are read-only
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid():
            return False

        profile = self._profiles[index.row()]

        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            # Toggle the hidden state
            profile.hidden = (value == Qt.CheckState.Checked.value)
            print(profile.hidden)
            self.dataChanged.emit(
                index, index, [Qt.ItemDataRole.CheckStateRole])
            return True

        return False

    def addProfile(self, profile: 'Profile'):
        self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
        self._profiles.append(profile)
        self.endInsertRows()

    def removeProfile(self, row: int):
        if 0 <= row < self.rowCount():
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._profiles[row]
            self.endRemoveRows()

    def setProfiles(self, profiles):
        """Replace the entire set of profiles in the model with a new list."""
        self.beginResetModel()
        self._profiles = profiles
        self.endResetModel()
