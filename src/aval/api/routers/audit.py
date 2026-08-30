from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from aval.application.services.dispute import DisputeService, DisputeVerdict
from aval.adapters.ucp.http_signatures import Rfc9421Verifier
from aval.api.authentication import authenticate_rfc9421


def _serialize_verdict(verdict: DisputeVerdict) -> dict[str, object]:
    return {
        "status": verdict.status,
        "reason_code": verdict.reason_code,
        "human_summary": verdict.human_summary,
        "post_commit_note": verdict.post_commit_note,
        "timeline": [
            {
                "id": event.id,
                "mandate_id": event.mandate_id,
                "event_type": event.event_type,
                "reason_code": event.reason_code,
                "human_summary": event.human_summary,
                "actor": event.actor,
                "occurred_at": event.occurred_at.isoformat(),
                "evidence_hash": event.evidence_hash,
                "revocation_epoch": event.revocation_epoch,
            }
            for event in verdict.timeline
        ],
    }


def create_audit_router(
    service: DisputeService, *, verifier: Rfc9421Verifier | None = None, can_read=None, mandate_exists=None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/audit/mandates/{mandate_id}")
    async def audit_timeline(mandate_id: str, request: Request = None) -> dict[str, object]:
        if verifier is not None:
            assert request is not None
            identity = authenticate_rfc9421(request, verifier)
            if mandate_exists is not None and not mandate_exists(mandate_id):
                raise HTTPException(404, detail={"code": "mandate_not_found"})
            if identity is None or (can_read is not None and not can_read(identity.id, mandate_id)):
                raise HTTPException(403, detail={"code": "reader_not_authorized"})
        return _serialize_verdict(service.reconstruct(mandate_id))

    @router.get("/audit/mandates/{mandate_id}/dispute")
    async def dispute(mandate_id: str, request: Request = None) -> dict[str, object]:
        if verifier is not None:
            assert request is not None
            identity = authenticate_rfc9421(request, verifier)
            if mandate_exists is not None and not mandate_exists(mandate_id):
                raise HTTPException(404, detail={"code": "mandate_not_found"})
            if identity is None or (can_read is not None and not can_read(identity.id, mandate_id)):
                raise HTTPException(403, detail={"code": "reader_not_authorized"})
        return _serialize_verdict(service.reconstruct(mandate_id))

    return router
