"""Ответ `link` и `unlink`: номера записей, подшитых в оба дела."""

from pydantic import BaseModel, Field


# Ответ `link` и `unlink`: номера записей, которые вызов подшил в оба дела.
#
# `kind` и ключ `other` здесь не повторяются: вызывающий прислал их сам, а `removed`
# у прежнего `unlink` был не нужен и вовсе — отказ приходит исключением, и успешный
# ответ всегда означал одно и то же значение (TRK-144).
#
# `key` — тот же адрес, что в запросе, по тому же правилу, что у `MutationView`: ответ
# должен читаться сам по себе. Ключ `other` в ответе не нужен: вызывающий его и так
# прислал, а `TRK-42#12` строится его собственным ключом плюс этим номером.
class LinkFilingView(BaseModel):
    """Entries filed by `link` or `unlink` on both sides of the link."""

    key: str
    entry: int = Field(
        description="Number of the `link_added` or `link_removed` entry in the case of `key`"
    )
    other_entry: int = Field(description="Number of the same entry in the case of `other`")
