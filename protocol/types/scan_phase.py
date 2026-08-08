from enum import Enum


class ScanPhase(str, Enum):
    WALKING = "walking"
    RECONCILING = "reconciling"
    INSERTING = "inserting"
    DONE = "done"
