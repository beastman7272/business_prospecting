"""add contacts and dossiers (Stage 2/3 wiring)

Revision ID: c1a2b3d4e5f6
Revises: eb03577ee49e
Create Date: 2026-07-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1a2b3d4e5f6'
down_revision = 'eb03577ee49e'
branch_labels = None
depends_on = None


def upgrade():
    # ### Stage 2: discovered contacts (per business) ###
    op.create_table(
        'contacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('business_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('company', sa.String(), nullable=True),
        sa.Column('confidence', sa.String(), nullable=True),
        sa.Column('why_relevant', sa.Text(), nullable=True),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('selected', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_contacts_business_id'),
                              ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_contacts_rank'),
                              ['rank'], unique=False)

    # ### Stage 3: deep-dive dossier (per contact) ###
    op.create_table(
        'dossiers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(), nullable=True),
        sa.Column('seniority_score', sa.Integer(), nullable=True),
        sa.Column('worth_deepdive', sa.Boolean(), nullable=True),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('currency_evidence', sa.Text(), nullable=True),
        sa.Column('reach', sa.Text(), nullable=True),
        sa.Column('background', sa.Text(), nullable=True),
        sa.Column('engagement', sa.Text(), nullable=True),
        sa.Column('org_inferences', sa.Text(), nullable=True),
        sa.Column('warnings', sa.Text(), nullable=True),
        sa.Column('raw_json', sa.Text(), nullable=True),
        sa.Column('generated_at', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contact_id'),
    )


def downgrade():
    op.drop_table('dossiers')
    with op.batch_alter_table('contacts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contacts_rank'))
        batch_op.drop_index(batch_op.f('ix_contacts_business_id'))
    op.drop_table('contacts')
