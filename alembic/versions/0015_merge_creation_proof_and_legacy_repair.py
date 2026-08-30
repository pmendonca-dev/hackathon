"""Duas cabeças que nasceram do mesmo pai, e uma linha só depois delas.

`0013_mandate_creation_proof` fez o mandato nascer com a assinatura de quem o criou;
`0013_repair_legacy_mandate_frequency` consertou bancos de demonstração carimbados na
cabeça sem a coluna de frequência. As duas partem de
`0012_merge_watches_and_browser_sessions` e não se tocam — uma escreve uma coluna de
prova, a outra repara uma coluna que já devia existir.

Sem esta junção `alembic upgrade head` recusa: com duas cabeças ele não sabe qual, e um
banco novo nunca chega a nenhuma das duas. Não há DDL aqui de propósito: juntar
históricos é uma afirmação sobre a ordem, não sobre o schema.

Revision ID: 0015_merge_creation_proof_and_legacy_repair
Revises: 0013_mandate_creation_proof, 0013_repair_legacy_mandate_frequency
"""

from __future__ import annotations

revision = "0015_merge_creation_proof_and_legacy_repair"
down_revision = ("0014_operator_sessions_and_journal", "0013_repair_legacy_mandate_frequency")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nada a fazer: as duas cabeças já deixaram o schema onde ele precisa estar."""


def downgrade() -> None:
    """Idem — desfazer a junção é voltar a ter duas cabeças, não desfazer DDL."""
