from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scanner:
    name: str
    driver: str
    mock: bool = False


@dataclass
class ScanOptions:
    scanner: Scanner
    source: str = "glass"
    dpi: int = 300
    color: str = "color"
    paper: str = "a4"
    deskew: bool = False
    blank_page_removal: bool = False
    pages: int = 1


class ScannerError(Exception):
    pass


class ScannerBackend(ABC):
    @abstractmethod
    def discover(self) -> list[Scanner]: ...

    @abstractmethod
    def scan(self, options: ScanOptions, output: Path) -> Path: ...

    @abstractmethod
    def cancel(self) -> None: ...
