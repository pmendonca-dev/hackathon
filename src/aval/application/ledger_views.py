"""Three readings of one trail.

The trail is written once. What differs per audience is what may be read back, and
the merchant view is the one that matters: it is built from a whitelist, never by
deleting fields from the full record. A blacklist forgets; a whitelist cannot leak a
field nobody remembered to hide.

A receipt that leaked the buyer's budget would leak the buyer.
"""

from __future__ import annotations

from typing import Any

from aval.infrastructure.sqlite.audit_ledger import LedgerEntry

# Everything a verifier legitimately needs to confirm a sale it took part in, and
# nothing about the mandate that funded it.
MERCHANT_VISIBLE_DETAIL = frozenset(
    {
        "agent_id",
        "checkout_id",
        "merchant_id",
        "category",
        "amount_minor_units",
        "currency",
        "scale",
        "decision",
        "reason_code",
        "reservation_id",
        "transaction_hash",
        "terms_hash",
        "proof_jti",
        "policy_version",
        "revocation_epoch",
        "settlement_reference",
    }
)

MERCHANT_REDACTIONS = (
    "mandate budget, ceiling and accumulated spend",
    "mandate identifier and policy history",
    "principal identity and display name",
    "revocation authority keys",
)

# What the buyer is shown about a purchase. Hashes and key ids are the auditor's job.
HUMAN_VISIBLE_DETAIL = frozenset(
    {
        "agent_id",
        "decision_handle",
        "escalation_id",
        "checkout_id",
        "merchant_id",
        "category",
        "amount_minor_units",
        "currency",
        "scale",
        "decision",
        "reason_code",
        "limit_minor_units",
        "ceiling_minor_units",
        "allowed_merchant_ids",
        "allowed_categories",
        "expires_at",
        "reason",
        "settlement_reference",
    }
)


def _pick(detail: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    return {key: value for key, value in detail.items() if key in allowed}


def human_entry(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "sequence": entry.sequence,
        "event_type": entry.event_type,
        "human_summary": entry.human_summary,
        "occurred_at": entry.occurred_at.isoformat(),
        "detail": _pick(dict(entry.detail), HUMAN_VISIBLE_DETAIL),
    }


def merchant_entry(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "event_type": entry.event_type,
        "occurred_at": entry.occurred_at.isoformat(),
        "sha256": entry.sha256,
        "detail": _pick(dict(entry.detail), MERCHANT_VISIBLE_DETAIL),
    }


def auditor_entry(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "sequence": entry.sequence,
        "mandate_id": entry.mandate_id,
        "event_type": entry.event_type,
        "human_summary": entry.human_summary,
        "actor": entry.actor,
        "occurred_at": entry.occurred_at.isoformat(),
        "detail": dict(entry.detail),
        "sha256": entry.sha256,
        "previous_sha256": entry.previous_sha256,
    }
