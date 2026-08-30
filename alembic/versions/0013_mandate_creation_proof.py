"""O mandato passa a nascer com a assinatura de quem o criou.

Até aqui a trilha provava que o agente ficou dentro do mandato e não provava que a
pessoa o criou. A prova de criação é um JWS ES256 de uma autoridade *holder* do próprio
mandato sobre os termos que ele nasce carregando, e vive numa tabela própria: o mandato
em si não muda de forma, e uma linha aqui não pode ser reescrita sem quebrar a cadeia
que a cita.

`creation_nonce` é único de propósito. Uma criação é replayável de um jeito que uma
revogação não é — repetir a mesma assinatura criaria um segundo mandato com os mesmos
termos, dobrando a capacidade de gasto da titular sem que ela assinasse duas vezes.

Revision ID: 0013_mandate_creation_proof
Revises: 0012_merge_watches_and_browser_sessions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_mandate_creation_proof"
down_revision = "0012_merge_watches_and_browser_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "mandate_creation_proofs" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "mandate_creation_proofs",
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), primary_key=True),
        sa.Column("kid", sa.String(), nullable=False),
        sa.Column("nonce", sa.String(), nullable=False),
        sa.Column("signed_jws", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ux_mandate_creation_proof_nonce", "mandate_creation_proofs", ["nonce"], unique=True
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "mandate_creation_proofs" not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_index("ux_mandate_creation_proof_nonce", table_name="mandate_creation_proofs")
    op.drop_table("mandate_creation_proofs")
