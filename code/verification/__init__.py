"""Stage 3 Deterministic Verifier package."""
from code.verification.conflict_resolver import (
    is_same_originating_source,
    resolve_claim_pair,
    resolve_event_conflict,
)
from code.verification.image_resolver import ImageClaimResolver
from code.verification.lifecycle_deduplicator import EventLifecycleDeduplicator

__all__ = [
    "is_same_originating_source",
    "resolve_claim_pair",
    "resolve_event_conflict",
    "ImageClaimResolver",
    "EventLifecycleDeduplicator",
]
