from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
TRACEABILITY = PROJECT_ROOT / "docs" / "verification" / "architecture-traceability.md"
REHEARSAL = PROJECT_ROOT / "docs" / "verification" / "clean-environment-rehearsal.md"


def test_architecture_traceability_covers_every_delivery_boundary():
    """Removing a protocol/security row must leave the delivery map incomplete."""
    content = TRACEABILITY.read_text(encoding="utf-8")

    for required in (
        "RFC 9421",
        "AP2 v0.2",
        "ACP delegated payment / vault token",
        "Live revocation",
        "Capture / MockCardPSP / receipts",
        "Audit / dispute",
        "Browser BFF / session / CSRF",
        "No browser secrets",
        "x402 — disabled",
        "Requirement | Route or service | Regression evidence",
    ):
        assert required in content


def test_clean_rehearsal_names_the_required_commands_and_legacy_repair():
    """A release rehearsal must be executable without guessing missing gates."""
    content = REHEARSAL.read_text(encoding="utf-8")

    for required in (
        "git clone",
        "git worktree",
        "uv sync",
        "--link-mode=copy",
        "alembic upgrade head",
        "npm --prefix web ci",
        "AVAL_OPERATOR_AUTHORITY_SEED",
        "uv run python -m pytest -q",
        "uv run python -m pytest tests/integration/e2e -q",
        "uv run python scripts/demo_smoke.py",
        "npm --prefix web test",
        "npm --prefix web run build",
        "npm --prefix web run lint",
        "Browser BFF",
        "0013_repair_legacy_mandate_frequency",
        "max_uses",
        "x402 is disabled",
    ):
        assert required in content


def test_delivery_docs_remain_pre_gate_without_placeholders_or_invented_results():
    """Preparation documents must prescribe evidence, not claim an unrun final gate."""
    content = f"{TRACEABILITY.read_text(encoding='utf-8')}\n{REHEARSAL.read_text(encoding='utf-8')}"

    assert "Delivery status: pre-gate" in content
    assert "does not assert that the final delivery gate has passed" in content
    for prohibited in ("TODO", "TBD", "<placeholder>", "Final gate: PASS"):
        assert prohibited not in content
