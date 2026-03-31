"""
Station Controllers
Each station has its own controller class
"""

from factory.stations.station1 import Station1Controller
from factory.stations.station2 import Station2Controller
from factory.stations.station3 import Station3Controller
from factory.stations.station6 import Station6
from factory.stations.station7 import Station7
from factory.stations.transfer import TransferStation, SyncedTransferStation
from factory.stations.warehouse import WarehouseController
from factory.stations.machining import (
    MachiningCenterController,
    MachiningBaseController,
    MachiningLidController,
)

__all__ = [
    "Station1Controller",
    "Station2Controller",
    "Station3Controller",
    "Station6",
    "Station7",
    "TransferStation",
    "SyncedTransferStation",
    "WarehouseController",
    "MachiningCenterController",
    "MachiningBaseController",
    "MachiningLidController",
]
