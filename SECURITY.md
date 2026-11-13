# Bezpečnost TenderScope

## Nahlášení chyby

Našli jste bezpečnostní chybu? **Nepište ji do veřejného issue.** Použijte na GitHubu
záložku **Security → Report a vulnerability** (soukromé hlášení), nebo napište správci repozitáře
přes jeho profil na GitHubu. Ozveme se do 7 dnů. Děkujeme.

Podporovaná je vždy jen poslední verze ve větvi `main`.

## Co aplikace chrání a před kým

TenderScope pracuje s **veřejnými daty státu** (zakázky, smlouvy, ARES). Citlivé jsou hlavně:

| Aktivum | Proč je cenné | Ochrana |
|---|---|---|
| API klíče (AI – Claude, OpenAI, Gemini, Mistral, OpenRouter…, Exa, Hlídač státu) | někdo by čerpal placený účet | jen v proměnných prostředí / `config.local.json`, nikdy v gitu; klíč nikdy nejde do prohlížeče |
| Admin heslo online verze | ovládání serveru (aktualizace, klíče) | konstantní porovnání, blokace po 5 chybách / 15 min, heslo jen v proměnné prostředí |
| Onboarding návštěvníků | odpovědi firmy o jejích plánech | oddělené podle náhodného ID prohlížeče, cizí profil vrací „nenalezeno“ |
| Peněženka (placená API) | útok botů na drahé endpointy | denní strop volání AI a Exa, rate limiting, návštěvníci bez hesla placená API vůbec nepoužívají |
| Server | zneužití k útokům do vnitřní sítě | ochrana proti SSRF u stahování webu firmy |

Útočníci, se kterými počítáme (podle přednášky „Bezpečný vibe coding“ a „Rizika v kyber prostoru“):
automatické skenery a boti, zvědavý uživatel (přepíše IČO v adrese), škodlivý obsah webu firmy
(prompt injection do AI), škodlivá cizí stránka v prohlížeči uživatele (CSRF, DNS rebinding),
dodavatelský řetězec (balíčky, GitHub Actions) a převzetí účtu na GitHubu.

## Jak je to zařízené (11 pravidel z přednášky)

1. **Tajemství** – klíče se čtou z proměnných prostředí (`.env` lokálně, *Environment* na Renderu).
   Klíče zadané v aplikaci se ukládají do `config.local.json`, který je v `.gitignore`. Starší verze je ukládaly
   do `config.json`; aplikace je při startu sama přesune. Vzor bez hodnot je v `.env.example`.
   V CI běží **gitleaks** nad celou historií.
2. **Přístup** – online verze je ve výchozím stavu jen ke čtení. Aktualizace dat, nastavení klíčů a diagnostika
   vyžadují admin heslo (kontrola na serveru, ne skrytím tlačítka). Onboarding je oddělený pro každý prohlížeč
   (test dvou uživatelů je v `tests/`).
3. **Vstupy** – všechny SQL dotazy jsou parametrizované. IČO, texty, odpovědi i URL se validují
   (`ts/bezpecnost.py`), velikost těla požadavku je omezená na 512 kB, POST přijímá jen `application/json`.
   Žádné `eval`, `exec`, `pickle`. CSV exporty jsou chráněné proti CSV injection. React escapuje výstup,
   `innerHTML` se nepoužívá.
4. **Balíčky** – jen 3 Python balíčky (`requests`, `ijson`, `anthropic`) se zamčenými verzemi
   a zámek `package-lock.json` pro frontend. V CI běží `pip-audit` a `npm audit`, Dependabot hlídá aktualizace.
5. **Data** – ukládají se jen veřejná data státu. Registr smluv obsahuje osobní údaje (jména podepisujících),
   proto data neukládáme do gitu a používáme je jen pro účely projektu. Ve vývoji a testech jsou syntetická data (`demo.py`).
6. **Prostředí** – vývoj (lokálně, `--demo`) a produkce (Render) mají oddělená data i klíče. Server dostupný
   zvenku se vždy spustí v režimu online verze (zápisy jen s heslem).
7. **Chyby** – uživatel dostane obecnou hlášku s kódem, detail jde jen do logu serveru. Kontrola oprávnění
   při výjimce **zamítá** (fail closed). Do logu se zapisují odepřené přístupy a chybná hesla, nikdy hesla a klíče.
   Bezpečnostní záznamy se nezobrazují v logu aplikace.
8. **AI agent** – pravidla pro AI asistenty jsou v `AGENTS.md`. Vynucuje je CI (testy, skenery), ne prompt.
9. **LLM funkce** – text z webu firmy je pro AI nedůvěryhodný vstup (v promptu označený jako data).
   Model nemá žádné nástroje ani cestu ven (nemůže nic odeslat, smazat ani stáhnout), jeho výstup se
   validuje JSON schématem a pravidly a nikdy se nespouští ani nevkládá jako HTML. „Smrtelná trojice“ tak
   není úplná: chybí cesta ven. Návštěvníci online verze bez hesla AI vůbec nevolají. Poskytovatele AI
   a adresu API mění jen správce; na online verzi smí adresa API vést jen na veřejný server přes HTTPS (SSRF).
10. **Nasazení** – HTTPS zajišťuje Render (HSTS se posílá za HTTPS proxy), bezpečnostní hlavičky
    (CSP, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy), žádný CORS, kontrola `Origin`
    a `Host`, rate limiting (120 požadavků/min, 10 náročných/min na IP), denní stropy placených API,
    neprozrazujeme verzi Pythonu. GitHub Actions mají jen `contents: read` a akce připnuté na SHA.
11. **Ověření** – `tests/test_bezpecnost.py` (nepřihlášený, špatné heslo, fail closed, dva uživatelé,
    SQL injection, path traversal, CSRF/CORS, DNS rebinding, SSRF, limity, hlavičky, tajemství v repozitáři)
    běží v CI při každém pushi spolu s pip-audit, npm audit, bandit a gitleaks.

## Vědomá rozhodnutí a zbytková rizika

- **Výběr AI poskytovatele**: do zvolené AI odchází veřejná data o firmě a odpovědi z dotazníku. Bezplatné tarify
  (Gemini, Groq, OpenRouter free, Cloudflare, Cohere, Z AI, NVIDIA, Gonka, OVHcloud, Kilo, LLM7) mohou data logovat
  nebo použít ke zlepšování modelů; aplikace na to u každého upozorní. Adresy předvoleb jsou pevné v kódu
  (ověřené podle awesome-free-llm-apis), měnit jde jen adresu Ollamy / vlastního API. Nejsoukromější je lokální Ollama.

- **Server** je `http.server` ze standardní knihovny (bez debug režimu, s časovým limitem spojení).
  Pro školní projekt s malým provozem stačí; při větším nasazení by se dal za reverzní proxy nebo přepsal na produkční framework.
- **Admin heslo** místo účtů: aplikace má jednoho správce. Při více uživatelích by se přešlo na hotové
  přihlášení (OAuth), vlastní systém účtů nepíšeme.
- **ID prohlížeče** pro onboarding není přihlášení. Kdo ho zná (stejný prohlížeč), vidí stejné profily.
  Pro veřejná data a anonymní návštěvníky je to přiměřené.
- **SSRF**: adresa webu se ověřuje před každým stažením i při přesměrování; teoretický útok DNS rebinding
  mezi ověřením a stažením zůstává. Server na Renderu nemá citlivou vnitřní síť.
- **XML** z Registru smluv se čte standardním parserem (bandit B314 je vědomě potlačen): Python s expat ≥ 2.4.1
  je odolný proti XML bombám a externí entity nerozbaluje. Zdrojem je oficiální server státu.
- **Bandit B608** (SQL z řetězců) je potlačen na třech místech, kde se do SQL skládají jen konstanty nebo
  zástupné znaky `?`; hodnoty jdou vždy jako parametry.
- **Rate limiting** je v paměti serveru, po restartu se nuluje. Denní strop AI chrání i po restartu
  jen spolu s limitem útrat nastaveným přímo u poskytovatele AI (doporučeno).
- **Zálohy**: databáze se dá kdykoli znovu stáhnout z veřejných zdrojů, onboardingové profily se dají
  stáhnout jako JSON. Na bezplatném Renderu se data při restartu ztrácí (viz README).

## Co dělat při incidentu

1. **Unikl klíč?** Nejdřív ho **zneplatněte** u poskytovatele (console.anthropic.com, platform.openai.com, aistudio.google.com, console.mistral.ai, openrouter.ai, dashboard.exa.ai,
   hlidacstatu.cz), pak zkontrolujte spotřebu a teprve potom čistěte historii gitu.
2. **Uniklo admin heslo?** Změňte `TS_ADMIN_HESLO` na Renderu (Environment) – služba se restartuje.
3. **Útok nebo vysoký provoz?** Na Renderu službu pozastavte (*Suspend*), zkontrolujte *Logs*.
4. Závažný incident lze nahlásit na CSIRT.CZ (csirt.cz). Osobní údaje: ÚOOÚ.
