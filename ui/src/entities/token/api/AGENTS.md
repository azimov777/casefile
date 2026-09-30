# src/entities/token/api

## Файлы

- `tokens.test.ts` — принадлежность токена человеку, вид строки по `kind`, жизнь сеанса, ключа и подключения
- `tokens.ts` — тип токена из контракта и его вид `TokenKind`, `isRevoked` (отзыв — это заполненный `revoked_at`), `isSession`, `isConnection`, `isKey` (вид — по `kind`, не по сроку), `isThisComputer` (`local-ui`), `isLive` (сеанс — по сроку, ключ и подключение — до отзыва), `belongsTo` (говорит от имени или выпущен человеком, TRK-114#12), ключи запросов и `tokensQueryOptions`: токены с отозванными страницами по курсору, `mine` сужает до своих
