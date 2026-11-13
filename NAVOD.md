# TenderScope – návod (Windows)

**TenderScope** je webová aplikace pro competitive intelligence ve veřejných zakázkách.
Zadáte libovolnou firmu (název nebo IČO) a aplikace z otevřených dat státu spočítá, jak je
konkurenceschopná: kolik vyhrává, s jakou úspěšností, za jaké ceny vůči předpokládané hodnotě,
u kterých zadavatelů, v jakých segmentech, proti komu soutěží a kde by mohla soutěžit teď.
Nově umí i **onboarding firmy**: z IČO sestaví profil firmy, položí 4 cílené otázky a hned ukáže
**Day-0 zpravodaj** – zakázky z posledních 14 dní, každou s dotazníkem vhodnosti (předmět, vzdálenost, velikost, čas…).

### Přechod z předchozí verze (máte už staženo)
1. V černém okně stiskněte **Ctrl+C** a okno zavřete.
2. Rozbalte nový `tenderscope.zip` **přes starou složku** (Windows: „Nahradit soubory v cíli“).
   Složka `data` se nepřepíše, stažená data zůstanou.
3. Spusťte **`TenderScope.bat`**. Při startu si doinstaluje novou knihovnu (`anthropic`), trvá to pár sekund.
4. **Data → Rychlá aktualizace.** Průběh se teď vypisuje každých 5 sekund („zpracováno N záznamů“).
   Jeden měsíc trvá zhruba 1–3 minuty. Dřív se zpracování zdánlivě zaseklo, protože program zbytečně
   procházel stovky dokumentů u každé zakázky a nic nevypisoval.

## 1. Instalace (jednou, cca 5 minut)

1. Nainstalujte **Python 3.10+** z https://www.python.org/downloads/
   – při instalaci **zaškrtněte „Add python.exe to PATH“**.
2. Rozbalte `tenderscope.zip`, např. do `C:\TenderScope`.
3. Dvakrát klikněte na **`TenderScope.bat`**. Při prvním spuštění se samo nainstaluje vše potřebné
   a aplikace se otevře v prohlížeči na adrese http://127.0.0.1:8765

Node.js **nepotřebujete**. Frontend (TypeScript + React) je už sestavený ve složce `web/dist`.

## 2. První spuštění s reálnými daty

1. V aplikaci otevřete záložku **Data** a klikněte na **Rychlá aktualizace**.
   Stáhnou se zakázky ze všech oborů za poslední 3 měsíce. Stažení měsíce trvá chvilku (desítky MB),
   zpracování zhruba 1–3 minuty na měsíc. Průběh vidíte v logu přímo na stránce, aktualizuje se každých 5 sekund.
2. Až se objeví „✓ hotovo“, vraťte se na **Firmy** a zadejte firmu.
3. Až budete chtít delší historii a ověřování vítězů v Registru smluv, spusťte **Plnou aktualizaci**
   (12 měsíců + Registr smluv). První plný běh trvá déle (dumpy Registru smluv mají stovky MB) a zabere
   několik GB na disku. Další běhy stahují a zpracovávají jen to, co se změnilo.

Okno s černou konzolí nechte otevřené – to je server aplikace. Zavřením okna aplikaci ukončíte.

**Demo:** `spustit.bat` → volba 2 spustí aplikaci s vymyšlenými firmami bez internetu (na ukázku).

## 3. Co aplikace ukazuje

| Část | Co znamená |
|---|---|
| **Skóre konkurenceschopnosti 0–100** | vážený průměr 5 složek, každá s vysvětlením (viz níže) |
| Vyhrané zakázky, účasti, win rate | win rate se počítá jen ze soutěží, kde zdroj uvádí i neúspěšné účastníky |
| Objem výher, medián zakázky | součet smluvních cen bez DPH |
| Cena vs. předpokládaná hodnota | medián poměru vítězné ceny k odhadu zadavatele, srovnaný s trhem ve stejných segmentech |
| Výhry po měsících | výhry / objem / účasti v čase |
| Segmenty | oddíly CPV, podíl firmy na objemu segmentu a její pořadí |
| Největší zákazníci | zadavatelé podle objemu |
| Graf ceny | každá zakázka jako bod – pod čárou = levnější než odhad |
| Přímé souboje | konkurenti, se kterými se firma potkala v téže soutěži, a kdo vyhrál |
| Hlavní rivalové | kdo vyhrává nejvíc ve stejných segmentech |
| Kde by mohla soutěžit teď | otevřené zakázky v jejích segmentech, zvýrazněné u stávajících klientů |
| Zakázky | seznam výher i neúspěchů s odkazem na NEN, „RS ✓“ = smlouva nalezena v Registru smluv |

**Skóre** (váhy): úspěšnost v soutěžích 25 % (win rate vs. medián trhu) · tržní pozice 25 % (percentil objemu
a podíl v segmentech) · cenová konkurenceschopnost 20 % (o kolik levněji než trh vítězí) · šíře klientské
základny 15 % (počet zadavatelů a závislost na největším) · dynamika 15 % (posledních 6 měsíců vs. předchozích 6).
Když pro složku chybí data, vynechá se a váhy se přepočítají. 65+ = vysoká, 40–64 = střední, pod 40 = nízká.

Záložka **Trh** ukazuje celý trh nebo vybraný segment: počty zakázek v čase, kdo vyhrává, regiony.

## 4. Onboarding firmy a Day-0 zpravodaj

Záložka **Onboarding** (nebo tlačítko „Onboarding a zpravodaj“ na profilu firmy):

1. **Firma** – zadáte IČO, volitelně web firmy, a kliknete **Spustit rešerši**.
2. **Recon agent** potichu (paralelně) vytáhne: ARES (název, sídlo, NACE), historii firmy v databázi zakázek
   (výhry, účasti, CPV, zadavatelé, kraje, typická velikost zakázky), Registr smluv, Hlídač státu (smlouvy za 3 roky,
   jen s tokenem) a text z webu firmy.
3. **Onboarding agent – fáze 1** shrne hypotézu („firma z Ostravy dělá silnice, medián zakázky 7 mil. Kč…“)
   a položí **4 otázky s klikacími předvolbami**: předmět a exkluze, rozpočet a čas na přípravu,
   regiony/dojezd (u IT místo toho model spolupráce), kvalifikace dle ZZVZ a konsorcia.
4. **Fáze 2** sestaví `company_profile` JSON: 8místné CPV (hlavní i vedlejší), klíčová a negativní slova,
   regiony CZ-NUTS 3, max. vzdálenost, rozpočet, min. dní na přípravu, kvalifikace, dealbreakery, whitelist zadavatelů.
   Profil jde na stránce upravit (CPV, kraje, rozpočet…), uložit a stáhnout jako JSON.
5. **Day-0 zpravodaj** – profil se okamžitě spáruje se zakázkami za posledních 14 dní (a se všemi ještě otevřenými).
   Každá zakázka má **dotazník vhodnosti** (kliknutím se rozbalí):

| Otázka | Jak se odpovídá | Váha |
|---|---|---|
| Odpovídá předmět tomu, co děláme? | shoda CPV s profilem + textová podobnost (TF-IDF) | 30 |
| Vyplatí se nám tam jezdit? | vzdálenost sídla od místa plnění (km po silnici, odhad) a regiony z profilu; u IT jen informativně | 20 |
| Sedí velikost na naši kapacitu? | předpokládaná hodnota vs. rozpočet z profilu | 15 |
| Stihneme připravit nabídku? | dny do lhůty vs. min. dní na přípravu | 10 |
| Známe zadavatele? | dosavadní klient / nový / blacklist | 10 |
| Jak silná je konkurence? | průměrný počet nabídek a dominance největšího dodavatele v segmentu | 10 |
| Splníme kvalifikaci, máme reference? | **odpovídáte vy** (ano / ne / nevím) | 5 |
| Máme v termínu volnou kapacitu? | **odpovídáte vy** (ano / ne / nevím) | 10 |

Výsledek: skóre 0–100 a verdikt **doporučeno** (70+), **zvážit** (50–69), **spíš ne**, nebo **nevhodné**, když platí
vylučující důvod: např. firma z Ostravy s limitem 100 km a zakázka v Mostě (~400 km), hodnota 3× nad kapacitou,
vyloučené slovo v názvu, odpověď „ne“ u kvalifikace nebo kapacity.

**Claude API (nepovinné, doporučené):** na stránce **Data → Klíče a Obsidian** vložte Claude API klíč
(console.anthropic.com → API Keys). Pak otázky a profil píše model **Claude Opus 5.5** podle vašeho promptu
(soubor `ts/prompty/onboarding_system.md`, jde upravit). Jeden onboarding stojí řádově jednotky korun.
Bez klíče (nebo když API selže) se použijí **pravidla** se stejným výstupem, aplikace tedy funguje vždy.
U profilu je vidět, kdo ho sestavil („Agent: Claude“ / „Agent: pravidla“).

**Proč ne PostgreSQL + pgvector:** pro jednoho uživatele na Windows by to znamenalo instalovat a spravovat databázový
server. TenderScope drží vše v jednom souboru SQLite a „embedding“ počítá lokálně (TF-IDF nad názvy zakázek a CPV),
na desítky tisíc zakázek to stačí a běží to za sekundy. Při nasazení pro víc firem by se přešlo na PostgreSQL + pgvector
a embeddingy z API, rozhraní by zůstalo stejné.

## 5. Export do Obsidianu (knowledge graph)

1. Na stránce **Data → Obsidian a Exa** vložte cestu ke složce svého trezoru, např.
   `C:\Users\<jméno>\OneDrive\...\9.semestr\CI\Obsidian\Jan`, a klikněte **Uložit**.
2. Otevřete profil firmy a klikněte **Export do Obsidianu**. Do trezoru se zapíše složka `TenderScope`
   (případně ji stáhnete jako ZIP a rozbalíte do trezoru ručně).
3. V Obsidianu otevřete `TenderScope/00_Prehled/<firma> – dossier` a graf (**Ctrl+G**). V nastavení grafu si
   přidejte **Groups** podle cesty (`path:TenderScope/01_Firmy` červeně, `/02_Zadavatele`, `/03_Zakazky`, `/06_Zdroje`…).

Struktura je stejná jako u DD trezoru (entity – zjištění – důkazy):

| Složka | Poznámky | Odkazuje na |
|---|---|---|
| 00_Prehled | dossier: skóre, KIQ, konkurenti, příležitosti, vložená mapa | vše |
| 01_Firmy | cílová firma a konkurenti (IČO, sídlo, souboje) | zakázky, zdroje |
| 02_Zadavatele | zákazníci a jejich zakázky | firma, zakázky |
| 03_Zakazky | zadavatel, vítěz, účastníci, segment, ceny, kritéria | firmy, zadavatel, segment, zdroje |
| 04_Segmenty | oddíly CPV, podíl a pořadí firmy | zakázky |
| 05_Zjisteni | F-…: fakt, zdroj, inference, alternativní hypotéza, dopad pro bid/no-bid | zdroje |
| 06_Zdroje | S-…: důkazy s Admiralty ratingem (A1 registry, C3 web) a odkazem | – |
| 07_Mapy | canvas mapa: firma, konkurenti (popisek = skóre soubojů), zákazníci, segmenty | – |

Každé tvrzení má odkaz na zdroj. Export více firem do stejného trezoru graf propojí přes společné
zadavatele, zakázky a konkurenty.

**Exa (nepovinné):** když vložíte Exa API klíč (dashboard.exa.ai), export i profil firmy dohledají na webu
zmínky o firmě a uloží je jako zdroje s ratingem C3. Bez klíče se použijí jen Google News.

## 6. Zdroje dat

| Zdroj | Registrace | Co z něj bereme |
|---|---|---|
| Registr veřejných zakázek – open data ISVZ (NEN, Věstník VZ, Tender arena, TENDERMARKET) | **ne** | zakázky, CPV, hodnoty, lhůty, kritéria, účastníci, vítězové, ceny |
| Registr smluv – open data (data.smlouvy.gov.cz) | **ne** | uzavřené smlouvy, křížové ověření vítězů |
| ARES | **ne** | název, sídlo, NACE, vznik/zánik; vyhledání firmy podle názvu, pokud není v datech |
| Google News RSS | **ne** | zprávy o firmě |
| Hlídač státu API | token zdarma | volitelně smlouvy firmy za 3 roky (onboarding) a textový brief (`config.json` → `hlidac_token`) |
| Web firmy | **ne** | popis činnosti pro onboarding (když zadáte URL) |
| Claude API (Anthropic) | klíč, placené dle spotřeby | volitelně Onboarding agent (otázky a profil) |

## 7. Co je potřeba ověřit na vašem počítači (důležité)

Aplikace byla vyvinuta a otestována na **umělých datech ve stejném formátu**, protože vývojové prostředí
nemělo přístup na státní servery. Adresa a formát ARES jsou ověřené na skutečné odpovědi. Registr smluv
a open data ISVZ jsou napsané podle oficiální dokumentace, ale skutečnou strukturu JSON v datech ISVZ
(mění se s verzemi 2.6 → 2.10) jsem neviděl. Extractor proto hledá pole podle významu.

Po první Rychlé aktualizaci zkontrolujte:
1. V logu u každého měsíce „RVZ MM/RRRR: N zaznamu…“ – N by mělo být v desítkách tisíc.
2. Na úvodní stránce nenulový počet dodavatelů a vítězných nabídek.
3. Profil známé firmy, např. hledejte „Alza“ nebo IČO 27082440.

Když něco nesedí (chybí ceny, CPV nebo vítězové): v aplikaci **Data → Diagnostika** zadejte IČO firmy, u které
to vidíte (výchozí je Škoda Auto 00177041), klikněte **Spustit diagnostiku → Kopírovat výpis** a výpis pošlete.
Ukáže skutečný záznam s touto firmou, kde v datech leží CPV, ceny a dodavatelé, a co z toho Extractor vyčetl;
pravidla v `ts/extractor.py` se podle něj doladí.

**Po nové verzi Extractoru** se při další aktualizaci už stažené měsíce zpracují znovu (nestahují se), aby se
opravy projevily i na starších datech. V logu uvidíte „Nová verze Extractoru…“.

## 8. Struktura projektu (pro tým / práci)

```
server.py            backend: HTTP server + JSON API + spouštění agentů na pozadí
ts/scout.py          agent Scout – stahování zdrojů, detekce nových dat, cache
ts/extractor.py      agent Extractor – CPV, lhůty, hodnoty, kritéria, účastníci, vítězové
ts/verifier.py       agent Verifier – IČO, duplicity, chybějící data, ověření v Registru smluv
ts/obsidian.py       export do Obsidianu (knowledge graph) a volitelné Exa
ts/api.py            agent Analyst pro aplikaci – profil firmy, skóre, souboje, trh
ts/onboarding.py     Recon + Onboarding agent, dotazník vhodnosti, Day-0 zpravodaj (TF-IDF párování)
ts/llm.py            volání Claude API (structured output JSON), záložní pravidla při chybě
ts/prompty/          systémový prompt Onboarding agenta (váš prompt + schéma fáze 2)
ts/analyst.py, ts/briefer.py, ts/orchestrator.py   textový brief (KIQ 1–5) pro příkazovou řádku
web/src/             frontend v TypeScriptu (React + Recharts)
web/dist/            sestavený frontend (to, co servíruje server.py)
data/                databáze SQLite a cache stažených souborů
```

API: `GET /api/hledat?q=`, `GET /api/firma/<IČO>`, `GET /api/trh?segment=`, `GET /api/stav`,
`POST /api/aktualizovat {"rezim":"rychle"|"plny"}`, `GET /api/beh`,
`POST /api/onboarding/start {"ico","web"}`, `POST /api/onboarding/dokoncit {"ico","odpovedi"}`,
`GET /api/onboarding/<IČO>`, `POST /api/onboarding/<IČO>/profil`, `GET /api/vhodnost/<IČO>?zakazka=<id>`.

**Úpravy frontendu** (potřebujete Node.js 18+): ve složce `web` spusťte `npm install`, pak `npm run dev`
(vývoj s živým náhledem na http://localhost:5173, server.py musí běžet) a nakonec `npm run build`
(přegeneruje `web/dist`).

## 9. Omezení

- Open data ISVZ vycházejí jednou měsíčně (~5. den) a začínají únorem 2024. Čerstvé výzvy z posledních dnů v nich nejsou.
- Win rate jde spočítat jen tam, kde zdroj uvádí i neúspěšné účastníky.
- Segment = oddíl CPV (první 2 číslice); firma soutěžící v úzké nice se srovnává se širším oddílem.
- Registr smluv obsahuje osobní údaje (GDPR). Data držte jen pro účely projektu.
- Zpravodaj „za posledních 14 dní“ se počítá od nejnovější zakázky v databázi. Open data vycházejí měsíčně,
  proto jde spíš o ukázku (backtest) než o denní hlídání; aplikace to u zpravodaje napíše.
- Vzdálenost je odhad: vzdušná čára × 1,25 mezi městem sídla (nebo krajským městem) a krajským městem místa plnění.
  Open data uvádějí místo plnění jen na úrovni kraje (NUTS 3).
- Historie firmy v onboardingu = to, co je v databázi (max. 12 měsíců zakázek, Registr smluv dle Plné aktualizace).
  Tři roky smluv dodá jen Hlídač státu s tokenem.
- Volání Claude API je napsané podle oficiální dokumentace a otestované na chybové stavy (neplatný klíč → pravidla),
  ale s platným klíčem jsem ho spustit nemohl. Kdyby něco nesedělo, onboarding automaticky přejde na pravidla.
