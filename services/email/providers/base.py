"""Provider interface."""
from abc import ABC, abstractmethod

from services.email.types import EmailMessage, SendResult


class EmailProvider(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, message: EmailMessage) -> SendResult: ...
