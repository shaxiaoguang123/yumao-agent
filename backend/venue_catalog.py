"""Fail-closed public state for the currently unconfigured trusted venue catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
import unicodedata

from backend.availability_matching.protocol_evidence import assess_evidence, current_evidence_report


_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z", re.ASCII)
_SCOPE_CONFIG_KEY = re.compile(r"[A-Z][A-Z0-9_]{2,63}\Z", re.ASCII)


class CatalogError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _safe_text(value: object, maximum: int, code: str) -> None:
    if (type(value) is not str or not 1 <= len(value) <= maximum or value != value.strip()
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in value)):
        raise CatalogError(code)


def _semantic_key(value: object) -> None:
    if type(value) is not str or not _KEY.fullmatch(value):
        raise CatalogError("invalid_venue_catalog")


@dataclass(frozen=True, slots=True)
class CatalogCourt:
    """A verified, semantic court option; it contains no platform identifier."""

    court_key: str
    display_name: str
    evidence_ref: str

    def __post_init__(self):
        _semantic_key(self.court_key)
        _safe_text(self.display_name, 100, "invalid_venue_catalog")
        _safe_text(self.evidence_ref, 160, "invalid_venue_catalog")

    def public_dto(self) -> dict:
        return {"court_key": self.court_key, "display_name": self.display_name,
                "evidence_ref": self.evidence_ref}


@dataclass(frozen=True, slots=True)
class CatalogVenue:
    """Semantic venue display data plus optional private scope/court associations."""

    venue_key: str
    display_name: str
    scope_config_key: str | None = field(default=None, repr=False)
    evidence_ref: str = ""
    courts: tuple[CatalogCourt, ...] = ()

    def __post_init__(self):
        _semantic_key(self.venue_key)
        _safe_text(self.display_name, 200, "invalid_venue_catalog")
        if self.scope_config_key is not None and (
                type(self.scope_config_key) is not str or not _SCOPE_CONFIG_KEY.fullmatch(self.scope_config_key)):
            raise CatalogError("invalid_venue_catalog")
        _safe_text(self.evidence_ref, 160, "invalid_venue_catalog")
        if type(self.courts) is not tuple or len(self.courts) > 128:
            raise CatalogError("invalid_venue_catalog")
        if any(type(court) is not CatalogCourt for court in self.courts):
            raise CatalogError("invalid_venue_catalog")
        if len({court.court_key for court in self.courts}) != len(self.courts):
            raise CatalogError("invalid_venue_catalog")
        if len({court.display_name for court in self.courts}) != len(self.courts):
            raise CatalogError("invalid_venue_catalog")
        if self.courts and self.scope_config_key is None:
            raise CatalogError("invalid_venue_catalog")

    def public_dto(self) -> dict:
        return {"venue_key": self.venue_key, "display_name": self.display_name,
                "evidence_ref": self.evidence_ref,
                "courts": [court.public_dto() for court in self.courts]}


@dataclass(frozen=True, slots=True)
class VenueCatalog:
    """Immutable versioned catalog, constructible only after reviewed binding evidence."""

    version: str
    source_client_build: str
    evidence_ref: str
    venues: tuple[CatalogVenue, ...]
    evidence_manifest: dict = field(repr=False, compare=False)
    _evidence_readiness: dict = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if type(self.version) is not str or not _VERSION.fullmatch(self.version):
            raise CatalogError("invalid_venue_catalog")
        _safe_text(self.source_client_build, 160, "invalid_venue_catalog")
        _safe_text(self.evidence_ref, 160, "invalid_venue_catalog")
        if type(self.venues) is not tuple or not 1 <= len(self.venues) <= 256:
            raise CatalogError("invalid_venue_catalog")
        if any(type(venue) is not CatalogVenue for venue in self.venues):
            raise CatalogError("invalid_venue_catalog")
        if len({venue.venue_key for venue in self.venues}) != len(self.venues):
            raise CatalogError("invalid_venue_catalog")
        report = assess_evidence(self.evidence_manifest)
        if not report["readiness"]["venue_directory_display"]:
            raise CatalogError("venue_catalog_evidence_incomplete")
        if any(venue.scope_config_key is not None for venue in self.venues) and not report["readiness"]["venue_catalog"]:
            raise CatalogError("venue_catalog_scope_evidence_incomplete")
        if any(venue.courts for venue in self.venues) and not report["readiness"]["plan_binding"]:
            raise CatalogError("venue_catalog_court_evidence_incomplete")
        object.__setattr__(self, "evidence_manifest", MappingProxyType({
            "schema_version": 1,
            "findings": MappingProxyType(dict(report["findings"])),
        }))
        object.__setattr__(self, "_evidence_readiness", dict(report["readiness"]))

    @property
    def evidence_readiness(self) -> dict:
        return dict(self._evidence_readiness)

    def public_options(self) -> dict:
        return {
            "catalog_status": "configured",
            "catalog_version": self.version,
            "source_state": "reviewed_protocol_evidence",
            "source_client_build": self.source_client_build,
            "evidence_ref": self.evidence_ref,
            "venues": [venue.public_dto() for venue in self.venues],
            "capabilities": {
                "display": True,
                # Directory metadata is ready, but explicit plan binding has no API yet.
                "plan_binding": False,
                # No recorded adapter or live query service is implemented in this release.
                "historical_availability": False,
                "live_availability": False,
            },
            "evidence_readiness": self.evidence_readiness,
            "blocking_evidence": [],
            "binding_blocking_evidence": [],
            "availability_blocking_evidence": [],
        }


class VenueCatalogService:
    """Expose semantic options only; default application wiring has no production entries."""

    def __init__(self, catalog: VenueCatalog | None = None):
        if catalog is not None and type(catalog) is not VenueCatalog:
            raise CatalogError("invalid_venue_catalog")
        self.catalog = catalog

    def public_options(self) -> dict:
        if self.catalog is not None:
            return self.catalog.public_options()
        report = current_evidence_report()
        return {
            "catalog_status": "not_configured",
            "catalog_version": None,
            "source_state": "protocol_evidence_partial",
            "venues": [],
            "capabilities": {
                "display": False,
                "plan_binding": False,
                "historical_availability": False,
                "live_availability": False,
            },
            "evidence_readiness": report["readiness"],
            "blocking_evidence": report["blocking_findings"]["venue_catalog"],
            "binding_blocking_evidence": report["blocking_findings"]["plan_binding"],
            "availability_blocking_evidence": report["blocking_findings"]["recorded_availability"],
        }
