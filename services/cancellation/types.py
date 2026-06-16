"""Types for cancellation flow."""
from enum import Enum


class Motivo(str, Enum):
    ERROR_CON_RELACION = "01"
    ERROR_SIN_RELACION = "02"
    NO_OPERACION = "03"
    GLOBAL = "04"


class CancellationStatus(str, Enum):
    NONE = "none"
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"
