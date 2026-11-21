from enum import Enum


class ShuffleMethod(str, Enum):
    TRUE_RANDOM = "true_random"
    AVOID_REPEATS = "avoid_repeats"
