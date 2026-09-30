"""token kind: session, key or oauth connection

Revision ID: bb05bcd1d657
Revises: 5c81e3a7d92b
Create Date: 2026-10-01 12:00:00.000000+00:00

Вид строки доступа (`TokenKind`, решения `TRK-469#24`, `#25`) — колонка `tokens.kind`.
До неё вид угадывался по сроку: срок был только у сеанса браузера. Подключению OAuth
(TRK-470) срок тоже нужен, и признак «есть срок — значит сеанс» перестаёт работать.

Заполнение существующих строк — по порядку, первое совпавшее правило:

- `expires_at` не пуст → `session` (сеанс браузера — единственный, у кого был срок);
- имя `local-ui` → `session` (ключ интерфейса этой машины — вход человека);
- имя с префиксом `oauth: ` → `oauth` (подключение TRK-448, до сих пор без срока);
- остальное → `key`.

Подключения, выданные до этой ревизии, срока не получают: их токены живут до ротации
refresh, а новый токен ротации уже выпускается со сроком.

Откат снимает колонку. Прежде он стирает срок у подключений: без колонки строка со сроком
снова читалась бы сеансом браузера — не уехала бы в архив и открыла бы вкладку по куке.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bb05bcd1d657"
down_revision: str | None = "5c81e3a7d92b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Имя ограничения собрано по соглашению `NAMING_CONVENTION` (`app/db/base.py`):
#: `ck_<таблица>_<имя перечисления>`.
CONSTRAINT = "ck_tokens_token_kind"
KINDS = ("session", "key", "oauth")


def upgrade() -> None:
    op.add_column("tokens", sa.Column("kind", sa.String(length=16), nullable=True))
    op.execute(
        "UPDATE tokens SET kind = CASE "
        "WHEN expires_at IS NOT NULL THEN 'session' "
        "WHEN name = 'local-ui' THEN 'session' "
        "WHEN left(name, 7) = 'oauth: ' THEN 'oauth' "
        "ELSE 'key' END"
    )
    op.alter_column("tokens", "kind", nullable=False)
    values = ", ".join(f"'{kind}'" for kind in KINDS)
    op.execute(f"ALTER TABLE tokens ADD CONSTRAINT {CONSTRAINT} CHECK (kind IN ({values}))")


def downgrade() -> None:
    op.execute("UPDATE tokens SET expires_at = NULL WHERE kind = 'oauth'")
    op.execute(f"ALTER TABLE tokens DROP CONSTRAINT {CONSTRAINT}")
    op.drop_column("tokens", "kind")
