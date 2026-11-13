"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-11-12
"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table('clients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tg_user_id', sa.BigInteger(), nullable=True),
    sa.Column('tg_username', sa.String(length=64), nullable=True),
    sa.Column('name', sa.String(length=100), server_default='', nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tg_user_id')
    )
    op.create_index(op.f('ix_clients_phone'), 'clients', ['phone'], unique=False)
    op.create_table('masters',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('tg_username', sa.String(length=64), nullable=True),
    sa.Column('tg_user_id', sa.BigInteger(), nullable=True),
    sa.Column('note', sa.Text(), server_default='', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tg_user_id')
    )
    op.create_table('services',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('short_name', sa.String(length=40), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('duration_min', sa.Integer(), nullable=False),
    sa.Column('price', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.CheckConstraint('duration_min > 0', name='services_duration_positive'),
    sa.CheckConstraint('price >= 0', name='services_price_nonneg'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('bookings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('master_id', sa.Integer(), nullable=False),
    sa.Column('service_id', sa.Integer(), nullable=True),
    sa.Column('client_id', sa.Integer(), nullable=True),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('price', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('note', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_by', sa.String(length=10), nullable=True),
    sa.Column('remind_24_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('remind_2_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("kind = 'block' OR (service_id IS NOT NULL AND client_id IS NOT NULL)", name='bookings_booking_has_client'),
    sa.CheckConstraint("kind IN ('booking', 'block')", name='bookings_kind_valid'),
    sa.CheckConstraint("status IN ('active', 'cancelled')", name='bookings_status_valid'),
    sa.CheckConstraint('ends_at > starts_at', name='bookings_end_after_start'),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.ForeignKeyConstraint(['master_id'], ['masters.id'], ),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bookings_client_id'), 'bookings', ['client_id'], unique=False)
    op.create_index(op.f('ix_bookings_master_id'), 'bookings', ['master_id'], unique=False)
    op.create_index(op.f('ix_bookings_starts_at'), 'bookings', ['starts_at'], unique=False)
    op.create_table('master_services',
    sa.Column('master_id', sa.Integer(), nullable=False),
    sa.Column('service_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['master_id'], ['masters.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('master_id', 'service_id')
    )
    op.create_table('shift_overrides',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('master_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=True),
    sa.Column('end_time', sa.Time(), nullable=True),
    sa.Column('note', sa.Text(), server_default='', nullable=False),
    sa.CheckConstraint('(start_time IS NULL AND end_time IS NULL) OR (start_time IS NOT NULL AND end_time > start_time)', name='shift_overrides_valid'),
    sa.ForeignKeyConstraint(['master_id'], ['masters.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('master_id', 'day', name='shift_overrides_master_day')
    )
    op.create_table('vacations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('master_id', sa.Integer(), nullable=False),
    sa.Column('date_from', sa.Date(), nullable=False),
    sa.Column('date_to', sa.Date(), nullable=False),
    sa.Column('note', sa.Text(), server_default='', nullable=False),
    sa.CheckConstraint('date_to >= date_from', name='vacations_range_valid'),
    sa.ForeignKeyConstraint(['master_id'], ['masters.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('weekly_shifts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('master_id', sa.Integer(), nullable=False),
    sa.Column('weekday', sa.SmallInteger(), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.CheckConstraint('end_time > start_time', name='weekly_shifts_end_after_start'),
    sa.CheckConstraint('weekday BETWEEN 0 AND 6', name='weekly_shifts_weekday_range'),
    sa.ForeignKeyConstraint(['master_id'], ['masters.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('master_id', 'weekday', name='weekly_shifts_master_weekday')
    )
    op.execute(
        """
        ALTER TABLE bookings ADD CONSTRAINT bookings_no_overlap
        EXCLUDE USING gist (master_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)
        WHERE (status = 'active')
        """
    )


def downgrade() -> None:
    op.drop_table('weekly_shifts')
    op.drop_table('vacations')
    op.drop_table('shift_overrides')
    op.drop_table('master_services')
    op.drop_index(op.f('ix_bookings_starts_at'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_master_id'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_client_id'), table_name='bookings')
    op.drop_table('bookings')
    op.drop_table('services')
    op.drop_table('masters')
    op.drop_index(op.f('ix_clients_phone'), table_name='clients')
    op.drop_table('clients')
