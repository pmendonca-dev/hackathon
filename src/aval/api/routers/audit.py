from __future__ import annotations

from fastapi import APIRouter

from aval.application.services.dispute import DisputeService, DisputeVerdict


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


def create_audit_router(service: DisputeService) -> APIRouter:
    router = APIRouter()

    @router.get("/audit/mandates/{mandate_id}")
    async def audit_timeline(mandate_id: str) -> dict[str, object]:
        return _serialize_verdict(service.reconstruct(mandate_id))

    @router.get("/audit/mandates/{mandate_id}/dispute")
    async def dispute(mandate_id: str) -> dict[str, object]:
        return _serialize_verdict(service.reconstruct(mandate_id))

    return router
