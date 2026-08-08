from enum import Enum


class QueueOrigin(str, Enum):
    USER = "user"
    AUTOFILL = "autofill"
