"""Three readings of one trail.

The trail is written once. What differs per audience is what may be read back, and
the merchant view is the one that matters: it is built from a whitelist, never by
deleting fields from the full record. A blacklist forgets; a whitelist cannot leak a
field nobody remembered to hide.

A receipt that leaked the buyer's budget would leak the buyer.
"""

from __future__ import annotations

from collections.abc import Callable
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
        # `policy_version` and `revocation_epoch` are deliberately absent. They move
        # with the mandate rather than with the sale, so two merchants comparing them
        # against timestamps get a linkage signal for the same buyer — and they buy the
        # merchant nothing, because the signed proof it verifies carries both already.
        "settlement_reference",
    }
)

# The same whitelist doctrine, one level up. Filtering fields but not events left a
# hole with the shape of the field filter: `payment_in_doubt` carries only fields the
# merchant may read, and still tells it that this buyer's money is uncertain — which is
# a fact about the buyer's processor, not about the sale. A seller is answered about
# the sale it took part in and about nothing else that happened to the person paying.
MERCHANT_VISIBLE_EVENTS = frozenset(
    {"purchase_committed", "purchase_settled", "purchase_declined"}
)

MERCHANT_REDACTIONS = (
    "mandate budget, ceiling and accumulated spend",
    "mandate identifier and policy history",
    "principal identity and display name",
    "revocation authority keys",
    "escalations, disputes and payment uncertainty of the buyer",
    "any identifier that correlates this buyer with another merchant",
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
        # Authorized, in confirmation, settled. A processor that never answered is
        # neither a success nor a refusal, and the person paying is the one who has to
        # be told that — a screen that rounds *unknown* to either is lying to them.
        "payment_state",
        # Which of the holder's keys signed this mandate into existence. The proof
        # itself stays with the auditor: the person needs to recognise their own key,
        # not to re-verify a signature their browser produced.
        "creation_kid",
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


def merchant_entry(
    entry: LedgerEntry, *, pairwise: Callable[[str, str], str] | None = None
) -> dict[str, Any]:
    """One sale, as the seller in it may read it.

    `pairwise` names the buyer the only way a merchant is allowed to know them: a
    handle that is stable at this shop and different at every other. Without it the
    merchant gets no buyer handle at all, which is what it had before — correct, and
    useless for recognising a returning customer.
    """
    detail = _pick(dict(entry.detail), MERCHANT_VISIBLE_DETAIL)
    merchant_id = detail.get("merchant_id")
    if pairwise is not None and entry.mandate_id and isinstance(merchant_id, str):
        detail["pairwise_id"] = pairwise(entry.mandate_id, merchant_id)
    return {
        "event_type": entry.event_type,
        "occurred_at": entry.occurred_at.isoformat(),
        "sha256": entry.sha256,
        "detail": detail,
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
