"""O operador passa a ter credencial que expira e rastro que se confere.

Duas tabelas, nenhuma delas capaz de mover dinheiro.

`operator_sessions` guarda o hash de uma credencial curta, trocada pelo token permanente
em `POST /operator/sessions`. O console do navegador deixa de carregar o token dentro do
bundle — um segredo permanente publicado numa página é um segredo permanente perdido.

`operator_journal` é a cadeia de hash do que uma credencial de operador fez. Ninguém
assina para operar, então a assinatura é substituída pela propriedade que dá para provar:
nada foi retirado depois. Escritas entram; leituras não, porque um diário que registrasse
as próprias leituras enterraria as três linhas que importam.

Revision ID: 0014_operator_sessions_and_journal
Revises: 0013_mandate_creation_proof
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_operator_sessions_and_journal"
down_revision = "0013_mandate_creation_proof"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "operator_sessions" not in tables:
        op.create_table(
            "operator_sessions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("token_hash", sa.String(), nullable=False, unique=True),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
        )
    if "operator_journal" not in tables:
        op.create_table(
            "operator_journal",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("sequence", sa.Integer(), nullable=False, unique=True),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False),
            sa.Column("detail", sa.Text(), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sha256", sa.String(), nullable=False),
            sa.Column("previous_sha256", sa.String(), nullable=False),
            sa.Column("canonical_payload", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "operator_journal" in tables:
        op.drop_table("operator_journal")
    if "operator_sessions" in tables:
        op.drop_table("operator_sessions")
