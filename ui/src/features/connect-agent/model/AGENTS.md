# src/features/connect-agent/model

## Файлы

- `client.ts` — клиент фрагментов как вид в адресе (`?client=`): порядок дорожки, умолчание Claude Code, разбор и запись параметра
- `client.test.ts` — незнакомое значение — умолчание, умолчание параметра не пишет, прочие параметры остаются
- `snippets.ts` — `connectionSnippets`: плагин Claude Code и Codex без ключа (команды установщика, вход OAuth, строки `config.toml` при чужом адресе, `--sparse .codex-plugin`, признак доступности OAuth), заголовки и JSON `mcpServers` с ключом для клиентов без OAuth, установка скила (`skill`: прочие агенты, строка `CASEFILE_SKILL_ONLY=1` в двух оболочках; без адреса и токена); кавычки bash/zsh, строки TOML
- `snippets.test.ts` — адрес как есть и другой адрес — другой текст, подстановка и токен, ни `Authorization` ни `trk_` во фрагментах Claude Code и Codex, `--sparse .codex-plugin`, строки адреса Codex, доступность OAuth, команды плагина совпадают с `install.sh` дословно, метка во фрагментах с ключом или ни в одном, кавычки bash/zsh, команды скила совпадают с `docs/agent-install.md` байт в байт, скил не зависит от адреса, токена и метки
