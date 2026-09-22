# src/features/connect-agent/model

## Файлы

- `client.ts` — клиент фрагментов как вид в адресе (`?client=`): порядок дорожки, умолчание Claude Code, разбор и запись параметра
- `client.test.ts` — незнакомое значение — умолчание, умолчание параметра не пишет, прочие параметры остаются
- `snippets.ts` — `connectionSnippets`: заголовки, команда Claude Code, секция и переменная Codex (bash/zsh и PowerShell), поля формы Codex, JSON `mcpServers`; кавычки bash/zsh и PowerShell, строки TOML
- `snippets.test.ts` — адрес как есть и другой адрес — другой текст, подстановка и токен, переменная Codex одна и та же в bash/zsh и PowerShell, метка во всех фрагментах или ни в одном, порядок флагов Claude Code, секрет не в файле Codex, кавычки PowerShell
