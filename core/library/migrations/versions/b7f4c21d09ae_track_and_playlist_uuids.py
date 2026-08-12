"""track and playlist uuids, and a nullable unique location

Revision ID: b7f4c21d09ae
Revises: 4bb990066375
Create Date: 2026-08-12 20:05:00.000000

"""
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f4c21d09ae'
down_revision: Union[str, Sequence[str], None] = '4bb990066375'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('song', schema=None) as batch_op:
        batch_op.add_column(sa.Column('uuid', sa.String(), nullable=True))
        batch_op.alter_column('location', existing_type=sa.String(), nullable=True)

    op.add_column('playlist', sa.Column('uuid', sa.String(), nullable=True))

    _mint('song')
    _mint('playlist')
    _free_duplicate_locations()

    with op.batch_alter_table('song', schema=None) as batch_op:
        batch_op.alter_column('uuid', existing_type=sa.String(), nullable=False)
        batch_op.create_index('ix_song_uuid', ['uuid'], unique=True)
        batch_op.create_index('ix_song_location', ['location'], unique=True)

    with op.batch_alter_table('playlist', schema=None) as batch_op:
        batch_op.alter_column('uuid', existing_type=sa.String(), nullable=False)
        batch_op.create_index('ix_playlist_uuid', ['uuid'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('playlist', schema=None) as batch_op:
        batch_op.drop_index('ix_playlist_uuid')
        batch_op.drop_column('uuid')

    op.execute(sa.text("UPDATE song SET location = '' WHERE location IS NULL"))

    with op.batch_alter_table('song', schema=None) as batch_op:
        batch_op.drop_index('ix_song_location')
        batch_op.drop_index('ix_song_uuid')
        batch_op.alter_column('location', existing_type=sa.String(), nullable=False)
        batch_op.drop_column('uuid')


def _mint(table: str) -> None:
    connection = op.get_bind()
    ids = connection.execute(sa.text(f'SELECT id FROM {table} WHERE uuid IS NULL')).scalars().all()
    for row_id in ids:
        connection.execute(
            sa.text(f'UPDATE {table} SET uuid = :uuid WHERE id = :id'), {'uuid': str(uuid4()), 'id': row_id}
        )


def _free_duplicate_locations() -> None:
    """A location was unique only by convention, so an older database can hold two rows for one file. The oldest keeps it."""
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE song SET location = NULL, found_on_disk = 0 WHERE location = ''"))
    connection.execute(
        sa.text(
            'UPDATE song SET location = NULL, found_on_disk = 0 '
            'WHERE location IS NOT NULL '
            'AND id NOT IN (SELECT MIN(id) FROM song WHERE location IS NOT NULL GROUP BY location)'
        )
    )
