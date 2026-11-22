"""site accounts: people register on the site, then create or join projects

* `site_users` — login + password of a person on the site;
* `panel_accounts.user_id` — which site account holds the access to the project;
* `panel_sessions` — a session of a site account with the chosen project (recreated: old sessions are dropped).

Data: every panel account that already had a password becomes a site account with the same login and password, so
people keep signing in as before (now without the project code). When one login was used in several projects, the
first account (by id) keeps it; the others get access back by a new link from the owner.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22 12:00:00
"""
import sqlalchemy as sa

from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('site_users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('login', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=256), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_site_users')),
    sa.UniqueConstraint('login', name=op.f('uq_site_users_login'))
    )
    with op.batch_alter_table('panel_accounts') as batch:
        batch.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch.create_foreign_key(op.f('fk_panel_accounts_user_id_site_users'), 'site_users', ['user_id'], ['id'],
                                 ondelete='SET NULL')
        batch.create_unique_constraint(op.f('uq_panel_accounts_user_id'), ['user_id', 'project_id'])

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, login, password_hash, COALESCE(password_set_at, created_at) "
                                "FROM panel_accounts WHERE password_hash IS NOT NULL ORDER BY id")).all()
    taken: set[str] = set()
    for account_id, login, password_hash, created_at in rows:
        if login in taken:
            continue
        taken.add(login)
        conn.execute(sa.text("INSERT INTO site_users (login, password_hash, created_at) VALUES (:l, :h, :c)"),
                     {"l": login, "h": password_hash, "c": created_at})
        user_id = conn.execute(sa.text("SELECT id FROM site_users WHERE login = :l"), {"l": login}).scalar_one()
        conn.execute(sa.text("UPDATE panel_accounts SET user_id = :u WHERE id = :a"), {"u": user_id, "a": account_id})

    op.drop_index(op.f('ix_panel_sessions_account_id'), table_name='panel_sessions')
    op.drop_table('panel_sessions')
    op.create_table('panel_sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['site_users.id'], name=op.f('fk_panel_sessions_user_id_site_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['account_id'], ['panel_accounts.id'], name=op.f('fk_panel_sessions_account_id_panel_accounts'),
                            ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('token_hash', name=op.f('pk_panel_sessions'))
    )
    op.create_index(op.f('ix_panel_sessions_user_id'), 'panel_sessions', ['user_id'], unique=False)
    op.create_index(op.f('ix_panel_sessions_account_id'), 'panel_sessions', ['account_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_panel_sessions_account_id'), table_name='panel_sessions')
    op.drop_index(op.f('ix_panel_sessions_user_id'), table_name='panel_sessions')
    op.drop_table('panel_sessions')
    op.create_table('panel_sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['panel_accounts.id'], name=op.f('fk_panel_sessions_account_id_panel_accounts'),
                            ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash', name=op.f('pk_panel_sessions'))
    )
    op.create_index(op.f('ix_panel_sessions_account_id'), 'panel_sessions', ['account_id'], unique=False)
    with op.batch_alter_table('panel_accounts') as batch:
        batch.drop_constraint(op.f('uq_panel_accounts_user_id'), type_='unique')
        batch.drop_constraint(op.f('fk_panel_accounts_user_id_site_users'), type_='foreignkey')
        batch.drop_column('user_id')
    op.drop_table('site_users')
