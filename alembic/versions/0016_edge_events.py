"""A caixa de saída entre os dois computadores.

O B fecha uma vigília sem ninguém olhando; o A é a única metade que alcança o Telegram.
Uma chamada direta entre eles perderia o resultado sempre que a rede estivesse fora no
segundo errado — e o que se perde é "o seu dinheiro se moveu". Então o B escreve a linha
na mesma transação que fecha a vigília, e o A a marca entregue só depois que o Telegram
aceitou a mensagem.

`id` é inteiro porque é um cursor antes de ser um nome: o A lê com `after=<id>`, e a
ordem precisa ser a ordem em que as coisas aconteceram.

`payload` atravessa para o computador que guarda a chave da OpenAI e termina numa
mensagem de chat. Ele carrega um principal, um desfecho, um título, um link e um valor —
nunca um token de pagamento, nunca uma assinatura.

Revision ID: 0016_edge_events
Revises: 0015_merge_creation_proof_and_legacy_repair
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_edge_events"
down_revision = "0015_merge_creation_proof_and_legacy_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "edge_events" not in tables:
        op.create_table(
            "edge_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("principal_id", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("delivered_at", sa.DateTime(timezone=True)),
        )
        op.create_index(
            "ix_edge_events_undelivered", "edge_events", ["delivered_at", "id"]
        )


def downgrade() -> None:
    op.drop_index("ix_edge_events_undelivered", table_name="edge_events")
    op.drop_table("edge_events")
