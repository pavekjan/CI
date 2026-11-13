# TenderScope – návod ke spuštění (Windows)

**TenderScope** je multiagentní systém pro competitive intelligence ve veřejných zakázkách.
Podporuje rozhodnutí: *„Máme se ucházet o tuto zakázku, a jak si stojíme proti konkurenci?“*

## 1. Instalace (jednou, cca 5 minut)

1. Nainstalujte **Python 3.10 nebo novější** z https://www.python.org/downloads/
   – při instalaci **zaškrtněte „Add python.exe to PATH“**.
2. Rozbalte ZIP `tenderscope.zip` např. do `C:\TenderScope`.
3. Dvakrát klikněte na **`spustit.bat`**. Při prvním spuštění si sám vytvoří prostředí
   a nainstaluje dvě knihovny (`requests`, `ijson`).

## 2. Spuštění

`spustit.bat` nabídne menu:

| Volba | Co udělá |
|---|---|
| 1 – Demo | Celý workflow na **umělých** datech (vymyšlené firmy), bez internetu. Vhodné na prezentaci a kontrolu, že vše funguje. |
| 2 – Ostrý běh IT | Stáhne skutečná data za 12 měsíců a vytvoří brief pro IT služby. |
| 3 – Ostrý běh stavebnictví | Totéž pro stavebnictví (CPV 45, 71). |
| 4 – Přepočítat | Nic nestahuje, jen znovu spočítá analýzu a brief z dat, která už máte. |
| 5 – Firma z ARES | Vypíše profil firmy podle IČO. |

Nebo z příkazové řádky (ve složce projektu):

```
.venv\Scripts\python tenderscope.py run --obor it --mesice 12 --ico 12345678
.venv\Scripts\python tenderscope.py run --tydenni --ano
.venv\Scripts\python tenderscope.py firma 27082440
.venv\Scripts\python tenderscope.py inspect
```

**První ostrý běh trvá déle** (desítky minut až hodina podle připojení): stahuje se ~12 měsíčních
ZIPů z Registru veřejných zakázek a XML dumpy Registru smluv (každý stovky MB). Vše se ukládá
do `data\cache`, takže další běhy jsou rychlé. Na disku počítejte s několika GB.

## 3. Výstupy (složka `vystupy`)

- `brief_RRRR-MM-DD.html` – brief pro vedení (otevře se v prohlížeči): shrnutí, doporučení BID / ZVÁŽIT / NO-BID,
  KIQ 1–5, konkurence, zprávy, kvalita dat. Dokud brief neschválíte, jmenuje se `..._NAVRH`.
- `zakazky.csv`, `konkurenti.csv`, `prilezitosti.csv` – tabulky pro Excel (oddělovač středník, čeština funguje).
- `data\tenderscope.db` – SQLite databáze se vším (lze otevřít např. v DB Browser for SQLite).

## 4. Nastavení (`config.json`, otevřete v Poznámkovém bloku)

| Položka | Význam |
|---|---|
| `obor` | `it` nebo `stavebnictvi` |
| `mesice` | kolik měsíců zpět (KIQ 1 = 12) |
| `smlouvy_mesice` | kolik měsíců Registru smluv stáhnout (výchozí 3, dumpy jsou velké) |
| `nase_ico` | IČO „naší“ firmy → KIQ 5 (win rate, cenová hladina, silné segmenty) |
| `hlidac_token` | volitelný token Hlídače státu |
| `schvaleni` | `true` = před finálním briefem se ptá člověka (lidské schválení) |
| `obory` | CPV prefixy a klíčová slova oboru – tady lze obor zúžit nebo rozšířit |

## 5. Zdroje dat – kde je a kde není registrace

| Zdroj | Registrace | Co z něj bereme | Adresa |
|---|---|---|---|
| Registr veřejných zakázek – open data ISVZ (obsahuje NEN, Věstník VZ, Tender arenu, TENDERMARKET) | **ne** | zakázky, CPV, hodnoty, lhůty, kritéria, účastníci, vítězové | `isvz.nipez.cz/.../opendata-rvz/VZ-MM-RRRR.zip` (měsíčně, ~5. den; od 2/2024) |
| Registr smluv – open data | **ne** | uzavřené smlouvy a skutečné ceny, ověření vítězů | `data.smlouvy.gov.cz/index.xml` + `dump_RRRR_MM.xml` |
| ARES | **ne** | profil konkurentů (název, sídlo, kraj, NACE, zánik) | `ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{IČO}` |
| Google News RSS | **ne** | kontext – zprávy o oboru a konkurentech | `news.google.com/rss/search?q=...` |
| Hlídač státu API | **ano, zdarma** (účet → https://www.hlidacstatu.cz/api → token) | doplňkový zdroj zakázek | `api.hlidacstatu.cz/api/v2/verejnezakazky/hledat` |

Token Hlídače státu vložte do `config.json` → `"hlidac_token": "váš_token"`. Bez něj systém funguje,
Hlídač je jen doplněk. ČSÚ DataStat jsme nezapojili – pro KIQ 1–5 není potřeba.

**Opravy oproti ukázkovému skriptu, který jste měli:** adresa ARES byla neúplná (`https://ares.gov.cz{ico}`),
správně je výše; obory NACE jsou v poli `czNace2008`. Hlídač státu chce hlavičku `Authorization: Token ...`
a endpoint `/api/v2/verejnezakazky/hledat`.

## 6. Jak systém funguje (agenti)

```
 Orchestrátor ─┬─ Scout ── stáhne RVZ/NEN/VVZ → Extractor (záznam po záznamu) → filtr oboru → DB
               ├─ Scout ── Hlídač státu (volitelně), Registr smluv, ARES, zprávy RSS → DB
               ├─ Verifier ── IČO checksum, duplicity, chybějící data, křížové ověření vítěze v Registru smluv,
               │              odlehlé ceny, zaniklé firmy (ARES)
               ├─ Analyst ── KIQ 1–5 + bid/no-bid skóre otevřených zakázek
               ├─ Briefer ── brief (MD + HTML) + CSV
               └─ lidské schválení → finální brief
```

| Agent | Soubor | Úkol |
|---|---|---|
| Scout | `ts/scout.py`, `ts/sources/*` | sleduje zdroje, stahuje, detekuje nové zakázky |
| Extractor | `ts/extractor.py` | CPV, lhůty, předpokládaná hodnota, kritéria, zadavatel, účastníci, vítězové |
| Verifier | `ts/verifier.py` | křížová kontrola zdrojů, duplicity, chybějící data |
| Analyst | `ts/analyst.py` | profily konkurentů, win rate, cenové benchmarky, trendy, příležitosti |
| Briefer | `ts/briefer.py` | denní/týdenní brief s doporučením |
| Orchestrátor | `ts/orchestrator.py` | pořadí kroků, log běhů (tabulka `behy`), lidské schválení |

**KIQ → kde v briefu:** KIQ 1 (co bylo vyhlášeno) · KIQ 2 (kdo vyhrává, ceny, win rate) · KIQ 3 (typické
hodnoty, kritéria, počty nabídek) · KIQ 4 (otevřené a zrušené zakázky + skóre) · KIQ 5 (naše pozice).

**Bid/no-bid skóre (0–100)** je záměrně pravidlové a vysvětlitelné: shoda s oborem, velikost vs. naše obvyklé
zakázky, intenzita konkurence v segmentu (průměrný počet nabídek), vztah k zadavateli (naše výhry / dominantní
konkurent), čas do podání. Každé doporučení má vypsané důvody.

## 7. Omezení, která je fér uvést v práci

- Open data RVZ vycházejí **jednou měsíčně** (~5. den), data začínají **únorem 2024**. Pro „dnešní“ výzvy je potřeba
  sledovat profily zadavatelů / NEN nebo Hlídač státu.
- Struktura JSON v RVZ se mění s verzí dokumentace (2.6 → 2.10). Extractor proto hledá pole podle významu, ne podle
  pevné cesty. Kdyby něco chybělo (např. prázdné CPV), spusťte `tenderscope.py inspect` – vypíše skutečné klíče
  prvního záznamu a co z něj Extractor vytáhl; pravidla se dolaďují v `ts/extractor.py`.
- Win rate jde spočítat jen tam, kde data uvádějí účastníky (u malých zakázek často chybí).
- Registr smluv obsahuje osobní údaje (GDPR) – data držte jen pro účely projektu.
- Demo data jsou vymyšlená a slouží jen k ukázce.

## 8. Automatické denní spouštění (volitelně)

Plánovač úloh Windows → Vytvořit základní úlohu → Denně 7:00 → Spustit program:
`C:\TenderScope\.venv\Scripts\python.exe`, argumenty `tenderscope.py run --ano --neotvirat`,
„Spustit v“: `C:\TenderScope`.
