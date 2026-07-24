from __future__ import annotations

from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path
import re
from typing import Any

from updater.errors import UpdaterError


_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@total_ordering
@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        if not isinstance(value, str):
            raise UpdaterError("INVALID_VERSION", "Версия должна быть строкой SemVer.")
        match = _SEMVER_RE.fullmatch(value)
        if not match:
            raise UpdaterError("INVALID_VERSION", f"Некорректная версия SemVer: {value!r}")
        prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
        for identifier in prerelease:
            if identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0"):
                raise UpdaterError(
                    "INVALID_VERSION",
                    f"Числовая prerelease-часть не может начинаться с нуля: {value!r}",
                )
        build = tuple(match.group(5).split(".")) if match.group(5) else ()
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)), prerelease, build)

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value += "-" + ".".join(self.prerelease)
        if self.build:
            value += "+" + ".".join(self.build)
        return value

    def _precedence(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._precedence() == other._precedence() and self.prerelease == other.prerelease

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        if self._precedence() != other._precedence():
            return self._precedence() < other._precedence()
        if not self.prerelease:
            return bool(other.prerelease)
        if not other.prerelease:
            return True
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            left_numeric = left.isdigit()
            right_numeric = right.isdigit()
            if left_numeric and right_numeric:
                return int(left) < int(right)
            if left_numeric != right_numeric:
                return left_numeric
            return left < right
        return len(self.prerelease) < len(other.prerelease)


@dataclass(frozen=True)
class VersionInfo:
    version: SemVer
    config_schema: int

    @classmethod
    def from_json(cls, payload: Any) -> "VersionInfo":
        if not isinstance(payload, dict) or set(payload) != {"version", "config_schema"}:
            raise UpdaterError(
                "INVALID_VERSION_FILE",
                "version.json должен содержать только version и config_schema.",
            )
        schema = payload["config_schema"]
        if isinstance(schema, bool) or not isinstance(schema, int) or schema < 1:
            raise UpdaterError("INVALID_VERSION_FILE", "config_schema должен быть целым числом >= 1.")
        return cls(version=SemVer.parse(payload["version"]), config_schema=schema)

    def to_json(self) -> dict[str, object]:
        return {"version": str(self.version), "config_schema": self.config_schema}


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    size: int
    sha256: str

    @classmethod
    def from_json(cls, payload: Any) -> "ManifestEntry":
        if not isinstance(payload, dict) or set(payload) != {"path", "size", "sha256"}:
            raise UpdaterError(
                "INVALID_MANIFEST",
                "Каждая запись manifest должна содержать только path, size и sha256.",
            )
        path = payload["path"]
        size = payload["size"]
        sha256 = payload["sha256"]
        if not isinstance(path, str) or not path:
            raise UpdaterError("INVALID_MANIFEST", "Путь manifest должен быть непустой строкой.")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise UpdaterError("INVALID_MANIFEST", f"Некорректный размер файла в manifest: {path!r}")
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            raise UpdaterError("INVALID_MANIFEST", f"Некорректный SHA-256 в manifest: {path!r}")
        return cls(path=path, size=size, sha256=sha256)


@dataclass(frozen=True)
class ValidatedPackage:
    zip_path: Path
    version: VersionInfo
    manifest: tuple[ManifestEntry, ...]
