"""Import external web-hosted references into the local reference library."""

from __future__ import annotations

from dataclasses import dataclass

from app.providers.nist_webbook import NISTWebBookClient, NISTWebBookReference
from matching.feature_store import MATCH_FEATURE_VERSION, compute_search_vector
from storage.database import Database
from utils.file_utils import normalize_source_path


@dataclass(frozen=True)
class ImportedWebReference:
    """Stored metadata for a successfully imported web reference."""

    ref_id: int
    name: str
    provider: str
    page_url: str
    jcamp_url: str


class WebReferenceImportService:
    """Application-layer helper for importing web references into SQLite."""

    def __init__(self, db: Database, *, nist_client: NISTWebBookClient | None = None) -> None:
        self._db = db
        self._nist_client = nist_client or NISTWebBookClient()

    def import_nist_reference(
        self,
        url: str,
        *,
        skip_existing: bool = True,
        commit: bool = True,
    ) -> ImportedWebReference:
        """Fetch one NIST WebBook IR reference and store it in the local DB."""
        reference = self._nist_client.fetch_reference(url)
        return self.store_nist_reference(
            reference,
            skip_existing=skip_existing,
            commit=commit,
        )

    def store_nist_reference(
        self,
        reference: NISTWebBookReference,
        *,
        skip_existing: bool = True,
        commit: bool = True,
    ) -> ImportedWebReference:
        """Store a previously fetched NIST WebBook reference in the local DB."""
        normalized_source = normalize_source_path(reference.page_url)

        if skip_existing:
            existing = next(
                (
                    row
                    for row in self._db.get_reference_identity_rows()
                    if str(row.get("source_norm", "")).strip() == normalized_source
                ),
                None,
            )
            if existing is not None:
                return ImportedWebReference(
                    ref_id=int(existing["id"]),
                    name=str(existing["name"]),
                    provider="nist_webbook",
                    page_url=reference.page_url,
                    jcamp_url=reference.jcamp_url,
                )

        ref_id = self._store_reference(reference, commit=commit)
        return ImportedWebReference(
            ref_id=ref_id,
            name=reference.name,
            provider="nist_webbook",
            page_url=reference.page_url,
            jcamp_url=reference.jcamp_url,
        )

    def _store_reference(self, reference: NISTWebBookReference, *, commit: bool) -> int:
        spectrum = reference.spectrum
        ref_id = self._db.add_reference_spectrum(
            name=reference.name,
            wavenumbers=spectrum.wavenumbers,
            intensities=spectrum.intensities,
            description=reference.description,
            source=reference.page_url,
            y_unit=spectrum.y_unit.value,
            source_provider="nist_webbook",
            external_id=reference.metadata.get("external_id", ""),
            sample_state=reference.metadata.get("state", ""),
            sampling_procedure=reference.metadata.get("sampling_procedure", ""),
            path_length=reference.metadata.get("path_length", ""),
            resolution=reference.metadata.get("resolution", ""),
            origin=reference.metadata.get("origin", ""),
            owner=reference.metadata.get("owner", ""),
            commit=False,
        )
        self._db.upsert_reference_feature(
            ref_id,
            feature_version=MATCH_FEATURE_VERSION,
            feature_vector=compute_search_vector(
                spectrum.wavenumbers,
                spectrum.intensities,
                y_unit=spectrum.y_unit,
            ),
            commit=False,
        )
        if commit:
            self._db.commit()
        return ref_id
