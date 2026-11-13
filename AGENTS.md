# Pravidla pro AI asistenty (Claude Code, Codex, Cursor, OpenCode…)

Tento soubor čtou AI agenti, kteří v repozitáři pracují. Pravidla jsou prosba, vynucuje je CI
(`.github/workflows/bezpecnost.yml`) a review člověka. Podrobnosti v `SECURITY.md`.

## Bezpečnostní pravidla projektu
- Žádná tajemství v kódu, v logu, v chybových hláškách ani v README. Čti je z proměnných prostředí
  (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`,
  `LLM_API_KEY`, `EXA_API_KEY`, `HLIDAC_TOKEN`, `TS_ADMIN_HESLO`) nebo z `config.local.json`.
  `config.json` je v gitu a klíče v něm musí zůstat prázdné.
- SQL jen parametrizované (`?`), nikdy skládání hodnot do řetězce.
- Každý nový endpoint v `server.py`: projde `_kontrola` (Host, Origin, rate limit), vstupy validuje
  přes `ts/bezpecnost.py`, admin akce volají `_vyzaduj_admin()`, data uživatele filtruje podle `vlastnik`.
- Kontrola oprávnění při chybě zamítá (fail closed). Uživateli obecná chyba, detail do logu.
- Žádné `eval`, `exec`, `pickle`, `subprocess` s uživatelským vstupem, žádné `innerHTML` / `dangerouslySetInnerHTML`.
- Server nestahuje URL od uživatele bez `bezpecnost.over_url` / `stahni_web` (SSRF).
- Výstup LLM je nedůvěryhodný: validovat schématem, nikdy nespouštět ani nevkládat jako HTML. LLM nedostane nástroje s cestou ven.
- Nové balíčky nejdřív navrhni a zdůvodni (existuje? sedí název? je udržovaný?), neinstaluj naslepo.
  Verze zamykej (`requirements.txt` s `==`, `package-lock.json`).
- Pracuj jen s demo daty (`python server.py --demo`). Nic nemaž (data, databázi, větve) bez schválení člověka.
- Pracuj na větvi, nepushuj do `main`, žádný `git push --force`.
- Testy v `tests/` neupravuj, neoslabuj ani nemaž, aby prošly. Změny testů ukaž zvlášť.
- Před dokončením spusť `python -m unittest discover -s tests -v` a ukaž výsledek. Nález skeneru nepotlačuj bez schválení.

## Jak projekt spustit
- `pip install -r requirements.txt` · `python server.py --demo` (umělá data) · testy: `python -m unittest discover -s tests -v`
- Frontend: `cd web && npm ci && npm run build` (výsledek `web/dist` se commituje).
