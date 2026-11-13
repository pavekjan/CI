# TenderScope

**TenderScope je aplikace, která z veřejně dostupných dat státu ukáže, jak si firma vede ve veřejných zakázkách,
s kým soutěží a o které aktuální zakázky by se jí vyplatilo ucházet.**

Vznikla jako školní projekt z předmětu Competitive Intelligence (CI). Nic se v ní nevymýšlí ručně:
všechno se počítá z otevřených dat, která stát zveřejňuje (Registr veřejných zakázek, Registr smluv, ARES).

---

## Obsah

1. [K čemu to je](#1-k-čemu-to-je)
2. [Co aplikace umí (záložky)](#2-co-aplikace-umí-záložky)
3. [Odkud jsou data](#3-odkud-jsou-data)
4. [Jak aplikaci spustit na svém počítači (Windows)](#4-jak-aplikaci-spustit-na-svém-počítači-windows)
5. [Online verze (bez instalace)](#5-online-verze-bez-instalace)
6. [Export do Obsidianu (knowledge graph)](#6-export-do-obsidianu-knowledge-graph)
7. [Umělá inteligence a nepovinné klíče](#7-umělá-inteligence-a-nepovinné-klíče)
8. [Bezpečnost](#8-bezpečnost)
9. [Časté otázky a problémy](#9-časté-otázky-a-problémy)
10. [Omezení](#10-omezení)
11. [Pro technicky zdatné](#11-pro-technicky-zdatné)

---

## 1. K čemu to je

Každý rok se v Česku zadají veřejné zakázky za stovky miliard korun. Informace o nich jsou veřejné,
ale roztroušené v tisících souborů. TenderScope je stáhne, uspořádá a odpoví na otázky typu:

- **Jak je firma X konkurenceschopná?** Kolik zakázek vyhrála, jak často uspěje, jestli nabízí levněji než ostatní.
- **Kdo jsou její konkurenti?** S kým se potkává v soutěžích a kdo v nich vyhrává.
- **Kdo jsou její zákazníci?** Kteří úřady, města a státní firmy jí zadávají nejvíc.
- **Co se děje na trhu?** Kolik se v daném oboru soutěží a kdo trh ovládá.
- **O co se má firma ucházet teď?** Seznam aktuálních zakázek, které jí sedí na obor, velikost i lokalitu.

Hodí se pro firmu, která chce sledovat konkurenci, i pro studenta, který potřebuje podložené CI analýzy.

---

## 2. Co aplikace umí (záložky)

Nahoře v aplikaci jsou čtyři záložky.

### Firmy (úvodní stránka)

Napíšete **název firmy nebo IČO** (osmimístné číslo firmy, najdete ho třeba na faktuře nebo v obchodním rejstříku)
a otevře se **profil firmy**:

| Co uvidíte | Co to znamená |
|---|---|
| **Skóre konkurenceschopnosti 0–100** | celková známka složená z 5 částí (níže). 65 a víc = vysoká, 40–64 = střední, pod 40 = nízká |
| Vyhrané zakázky a objem | kolik zakázek firma vyhrála a za kolik korun (bez DPH) |
| Úspěšnost (win rate) | z kolika soutěží, kterých se zúčastnila, vyšla jako vítěz |
| Cena vs. odhad | jestli firma vyhrává s cenou nižší, nebo vyšší, než zadavatel předpokládal |
| Výhry po měsících | graf, jak se firmě daří v čase |
| Segmenty | obory podle číselníku CPV (např. „stavební práce“, „IT služby“) a podíl firmy v nich |
| Největší zákazníci | zadavatelé, od kterých má firma nejvíc zakázek |
| Přímé souboje | konkurenti, se kterými se potkala ve stejné soutěži, a kdo vyhrál |
| Hlavní rivalové | kdo vyhrává nejvíc ve stejných oborech |
| Kde by mohla soutěžit teď | otevřené zakázky v jejích oborech |
| Seznam zakázek | všechny výhry i prohry s odkazem na originál |

**Jak se počítá skóre:** úspěšnost v soutěžích 25 %, pozice na trhu 25 %, cena 20 %, počet a rozložení zákazníků 15 %,
vývoj za posledních 6 měsíců 15 %. U každé části je napsané, z čeho vychází. Když pro některou část chybí data,
vynechá se a ostatní se přepočítají.

### Onboarding

Průvodce, který z jednoho IČO sestaví **profil firmy** a hned ukáže **první zpravodaj zakázek** („Day-0 zpravodaj“).

1. Zadáte **IČO** a případně **web** firmy.
2. Aplikace sama dohledá, co o firmě ví stát: sídlo, obor podnikání, dosavadní zakázky, smlouvy, text z webu.
3. Napíše shrnutí („firma z Ostravy, dělá silnice, typická zakázka 7 mil. Kč…“) a položí **4 otázky**
   s předvyplněnými odpověďmi na kliknutí: co firma dělá a nedělá, jak velké zakázky zvládne,
   kam je ochotná jezdit a jaké má certifikace.
4. Z odpovědí sestaví profil (obory, regiony, rozpočet, vylučující podmínky). Profil jde ručně upravit a stáhnout.
5. **Zpravodaj** ukáže zakázky z posledních 14 dní a ty, které jsou ještě otevřené. Každá má
   **dotazník vhodnosti** se skóre 0–100 a verdiktem *doporučeno / zvážit / spíš ne / nevhodné*.

Dotazník hodnotí:

| Otázka | Jak se odpovídá |
|---|---|
| Odpovídá předmět tomu, co děláme? | automaticky podle oboru a textu zakázky |
| Vyplatí se nám tam jezdit? | automaticky podle vzdálenosti od sídla (firma z Ostravy nepojede stavět do Mostu) |
| Sedí velikost na naši kapacitu? | automaticky podle hodnoty zakázky a rozpočtu z profilu |
| Stihneme připravit nabídku? | automaticky podle počtu dní do termínu |
| Známe zadavatele? | automaticky podle historie |
| Jak silná je konkurence? | automaticky podle počtu nabídek v oboru |
| Splníme kvalifikaci? | **odpovídáte vy** (ano / ne / nevím) |
| Máme volnou kapacitu? | **odpovídáte vy** (ano / ne / nevím) |

### Trh

Přehled celého trhu nebo vybraného oboru: kolik zakázek se zadává v čase, kdo vyhrává nejvíc, ve kterých krajích.

### Data

Správa dat a nastavení:

- **Rychlá aktualizace** stáhne zakázky za poslední 3 měsíce (pár minut).
- **Plná aktualizace** stáhne 12 měsíců a navíc Registr smluv (poprvé desítky minut, pak už jen novinky).
- **Umělá inteligence** slouží k výběru AI pro onboarding (Claude, ChatGPT, Gemini, Mistral, OpenRouter, Ollama…), viz kapitola 7.
- **Obsidian a Exa** slouží k nastavení exportu do Obsidianu (viz níže).
- **Diagnostika** pomáhá najít chybu, když něco v datech nesedí.
- **Online verze** obsahuje políčko pro heslo správce (jen na verzi běžící na internetu).

---

## 3. Odkud jsou data

Všechno jsou **otevřená data státu**, která smí použít kdokoli. Nic se nestahuje z placených databází.

| Zdroj | Co z něj aplikace bere | Potřeba registrace |
|---|---|---|
| Registr veřejných zakázek (ISVZ, nipez.cz): data z NEN, Věstníku a dalších systémů | zakázky, obory (CPV), předpokládané hodnoty, termíny, účastníci, vítězové, ceny | ne |
| Registr smluv (smlouvy.gov.cz) | skutečně uzavřené smlouvy, ověření vítězů | ne |
| ARES (obchodní rejstřík a živnostenský rejstřík) | název, sídlo, obor podnikání firmy | ne |
| Google News | zprávy o firmě | ne |
| Hlídač státu | smlouvy firmy za 3 roky (pro onboarding) | token zdarma, nepovinné |
| Web firmy | popis činnosti (pro onboarding) | ne |

Data se ukládají do jednoho souboru na vašem počítači (`data/tenderscope.db`). Na GitHubu nejsou, protože jsou velká
a dají se kdykoli stáhnout znovu tlačítkem **Aktualizace**.

---

## 4. Jak aplikaci spustit na svém počítači (Windows)

Zvládne to každý, programovat nemusíte. Potřebujete jen Python (zdarma).

### Krok 1: Nainstalujte Python (jednou)

1. Otevřete https://www.python.org/downloads/ a klikněte na žluté tlačítko **Download Python**.
2. Spusťte stažený soubor. **Důležité: dole zaškrtněte „Add python.exe to PATH“**, pak klikněte **Install Now**.

### Krok 2: Stáhněte aplikaci

1. Na této stránce GitHubu klikněte nahoře na zelené tlačítko **Code** a pak na **Download ZIP**.
2. Stažený soubor rozbalte (pravým tlačítkem → **Extrahovat vše**), třeba do `C:\TenderScope`.

### Krok 3: Spusťte

1. Ve složce dvakrát klikněte na **`TenderScope.bat`**.
2. Poprvé se otevře černé okno a chvíli se instaluje, co je potřeba (asi 1–2 minuty).
3. Pak se sama otevře aplikace v prohlížeči na adrese http://127.0.0.1:8765

**Černé okno nechte otevřené**, to je „motor“ aplikace. Když ho zavřete, aplikace se vypne.

### Krok 4: Stáhněte data

1. V aplikaci klikněte na záložku **Data** a pak na **Rychlá aktualizace**.
2. Uvidíte průběh. Jeden měsíc dat trvá zhruba 1–3 minuty. Až se objeví **✓ hotovo**, můžete začít.
3. Na záložce **Firmy** zadejte třeba „Škoda Auto“ nebo IČO `00177041`.

**Ukázka bez internetu:** dvojklik na `spustit.bat` → volba 2 spustí aplikaci s vymyšlenými firmami.

---

## 5. Online verze (bez instalace)

Aplikaci jde zdarma provozovat na internetu přes službu **Render.com**, takže ji ostatní otevřou jen přes odkaz.

**Jak online verze funguje:**
- Kdokoli s odkazem může hledat firmy, prohlížet trh a dělat onboarding.
- Aktualizovat data, měnit klíče a spouštět diagnostiku může jen **správce s heslem** (záložka Data → Online verze).
- Bezplatný server po 15 minutách bez návštěvy „usne“. První otevření pak trvá asi minutu, pak už běží normálně.
- Server si nepamatuje soubory mezi restarty, proto si data při startu načte ze zabalené databáze
  (složka `predpripravena_db`), nebo je stáhne znovu.

**Jak ji zprovoznit (správce, jednou):**
1. Na svém počítači ve složce aplikace dvakrát klikněte na **`pripravit_db.bat`**. Vytvoří zmenšenou kopii dat
   `predpripravena_db/tenderscope.db.gz` a tu nahrajte na GitHub spolu s aplikací.
   **Tento krok je důležitý:** server zakázek (isvz.nipez.cz) z cloudových serverů často neodpovídá,
   takže online verze si zakázky sama stáhnout nemusí. Aplikace to po dvou neúspěšných pokusech pozná a dál to nezkouší.
   Na GitHub soubor nahrajete příkazem `git add -f predpripravena_db/tenderscope.db.gz`, pak `git commit` a `git push`.
2. Na https://render.com klikněte **Get Started** a přihlaste se přes **GitHub**.
3. Klikněte **New → Blueprint** a vyberte tento repozitář.
4. Render se zeptá na **TS_ADMIN_HESLO**: vymyslete si heslo správce. Ostatní políčka můžete nechat prázdná.
5. Klikněte **Deploy Blueprint**. Za 3–5 minut dostanete adresu `https://….onrender.com`.

Každá další změna nahraná na GitHub se na Renderu sama projeví během pár minut.

### Aby byla online data aktuální

Server se zakázkami (isvz.nipez.cz) z cloudových serverů často neodpovídá, takže Render si zakázky sám
nestáhne. Data proto stahuje jiný počítač a nahrává je na GitHub do zvláštní větve **`data`**
(obsahuje jen jeden soubor a pokaždé se přepíše, takže repozitář neroste). Render si je při každém startu
načte (`TS_DB_URL` v `render.yaml`). Bezplatný Render se po 15 minutách bez návštěvy uspí a při další
návštěvě znovu nastartuje, takže nová data má prakticky hned.

Práce je rozdělená na dvě části, protože server se zakázkami (ISVZ) odpovídá jen počítačům v Česku:

**1. Registr smluv – automaticky každé ráno na GitHubu (Actions → Aktualizace dat).** Nic nemusíte mít
zapnuté. Historie za 3 roky se doplňuje po částech (asi 8 měsíců za jeden běh), takže je kompletní zhruba
za týden. Zakázky z ISVZ tady skončí hláškou „neodpovídá“ a přeskočí se – to je v pořádku.

**2. Zakázky (RVZ) – z vašeho počítače, stačí jednou za měsíc** (nový měsíc ISVZ zveřejní kolem
10. dne): dvakrát klikněte na **`aktualizovat_online.bat`**. Stáhne aktuální online databázi z větve
`data` (i se smlouvami, které do ní doplnil GitHub), přidá do ní zakázky za 12 měsíců a nahraje ji zpět.
Nespouštějte ho mezi 5:00 a 6:30 ráno, kdy běží aktualizace na GitHubu. Automatické spouštění (každé druhé
pondělí), v PowerShellu ve složce aplikace jednou:

```powershell
$a = New-ScheduledTaskAction -Execute "$PWD\aktualizovat_online.bat" -Argument "/tichy" -WorkingDirectory "$PWD"
Register-ScheduledTask -TaskName "TenderScope data" -Action $a -Trigger (New-ScheduledTaskTrigger -Weekly -WeeksInterval 2 -DaysOfWeek Monday -At 9am)
```
(Počítač musí být v tu dobu zapnutý. Zrušení: `Unregister-ScheduledTask -TaskName "TenderScope data"`.)

**Kolik dat se stahuje:** zakázky (RVZ) za 12 měsíců a Registr smluv za 36 měsíců. Z Registru smluv se
u starších měsíců ukládá jen souhrn po firmách (počet a objem smluv po měsících a hlavní odběratelé), celé
smlouvy jen za poslední 3 měsíce – jinak by se databáze na bezplatný server nevešla. **První spuštění trvá
dlouho** (stahují se desítky GB, počítejte s několika hodinami), další běhy jen doplní nové měsíce.

**Proč má firma v soutěžích (RVZ) málo výher:** v RVZ jsou hlavně větší soutěže. Malé zakázky a objednávky
(typicky e-shopy jako Alza) tam nejsou, ale jsou v Registru smluv. Profil firmy proto ukazuje obojí zvlášť
a u každého zdroje období. S tokenem Hlídače státu (`HLIDAC_TOKEN`, zdarma) ukáže i počet smluv za celou historii.

**Segment „neuvedeno“:** asi 70 % záznamů RVZ nemá vyplněné CPV. Aplikace segment odhadne podle názvu
zakázky (model se učí ze zakázek, které CPV mají; přesnost kolem 93 %) a označí ho jako *odhad*. Zbytek
může volitelně zařadit AI (`aktualizovat_online.bat` ji použije, když je na stránce Data nastavená; posílá
se jen veřejný název a druh zakázky).

**Kvalifikace (obrat, reference):** zadávací dokumentace není v otevřených datech strojově dostupná, proto
zpravodaj kvalifikaci odhaduje: zadavatel smí požadovat obrat nejvýš 2× předpokládanou hodnotu (ZZVZ § 78),
obrat firmy se bere z profilu (pole *Roční obrat*), jinak z veřejných tržeb (RVZ + Registr smluv za 12 měsíců),
a reference = vyhrané zakázky ve stejném oboru za 3 roky. Pokud zdroj podmínky účasti uvádí, ukážou se.
Zakázky, na které firma zjevně nedosáhne, dostanou verdikt *nevhodné*. Přesné podmínky vždy ověřte v dokumentaci
(odkaz *Detail a zadávací dokumentace*).

**Knowledge graph:** v profilu každé firmy je interaktivní graf (zákazníci, konkurenti, obory, zakázky, zdroje).
Kliknutím uzel otevřete, tažením ho posunete. Export do Obsidianu zůstává.

**Jak čerstvá data vůbec jsou:** zakázky (open data ISVZ/RVZ) zveřejňuje stát po **měsících**. Soubor za
uplynulý měsíc vychází během následujícího měsíce a poslední měsíce se ještě doplňují, takže zakázky jsou
typicky do konce minulého měsíce. **Registr smluv** se doplňuje **denně** (smlouvy do včerejška).
Úplně čerstvé zakázky po dnech nabízí API Hlídače státu (token zdarma, `HLIDAC_TOKEN`).

---

## 6. Export do Obsidianu (knowledge graph)

[Obsidian](https://obsidian.md) je bezplatný program na poznámky, který umí zobrazit **graf znalostí**:
poznámky jako body a odkazy mezi nimi jako čáry. TenderScope do něj umí vyexportovat celou analýzu firmy.

1. Na záložce **Data → Obsidian a Exa** vložte cestu ke složce svého Obsidian trezoru a klikněte **Uložit**.
   (Na online verzi se tento krok přeskakuje, export se stáhne jako ZIP, který rozbalíte do trezoru.)
2. Otevřete profil firmy a klikněte **Export do Obsidianu**.
3. V Obsidianu otevřete složku `TenderScope`, poznámku *dossier* a graf (**Ctrl+G**).

Co v exportu je:

| Složka | Obsah |
|---|---|
| 00_Prehled | souhrnná zpráva o firmě (dossier) |
| 01_Firmy | cílová firma a konkurenti |
| 02_Zadavatele | zákazníci (úřady, města, státní firmy) |
| 03_Zakazky | jednotlivé zakázky: kdo zadal, kdo vyhrál, za kolik |
| 04_Segmenty | obory a podíl firmy v nich |
| 05_Zjisteni | zjištění: fakt, zdroj, co z toho plyne a dopad pro rozhodnutí |
| 06_Zdroje | důkazy s hodnocením spolehlivosti (Admiralty rating) a odkazem |
| 07_Mapy | vizuální mapa vztahů (canvas) |

Každé tvrzení odkazuje na svůj zdroj. Když vyexportujete víc firem do stejného trezoru, graf je propojí
přes společné zákazníky, zakázky a konkurenty.

---

## 7. Umělá inteligence a nepovinné klíče

Aplikace funguje i **bez jakéhokoli klíče**. Klíče jen přidávají funkce navíc.

### Výběr umělé inteligence (AI) pro onboarding

Otázky a profil firmy v onboardingu může psát umělá inteligence. **Kterou použijete, si vyberete** v záložce
**Data → Umělá inteligence (onboarding agent)**:

**Placené (podle spotřeby):**

| Poskytovatel | Kde vzít klíč | Poznámka |
|---|---|---|
| **Anthropic Claude** | console.anthropic.com → API Keys | výchozí volba |
| **OpenAI (ChatGPT)** | platform.openai.com → API keys | předplatné ChatGPT Plus k API nestačí |
| **Mistral AI** | console.mistral.ai → API Keys | evropská firma |
| **OpenRouter** | openrouter.ai → Keys | jeden klíč na stovky modelů různých firem |

**Zdarma (bezplatné tarify)** – adresy a limity podle seznamu
[awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) (stav 11. 11. 2026, limity se mění):

| Poskytovatel | Klíč | Limit zdarma | Poznámka |
|---|---|---|---|
| **Google Gemini** | nutný (aistudio.google.com) | podle účtu | v EU se dotazy nepoužívají k tréninku; pro aplikaci pro veřejnost v EU podmínky chtějí placený tarif |
| **Groq** | nutný (console.groq.com) | 30/min, 1 000/den | velmi rychlé, bez karty |
| **OpenRouter – modely zdarma** | nutný (openrouter.ai) | 20/min, 50/den | `openrouter/free` vybere volný model |
| **Cloudflare Workers AI** | API token + Account ID | 10 000 „neuronů“/den | po vyčerpání nic neúčtuje, jen odmítne |
| **Cohere** | nutný (dashboard.cohere.com) | 1 000 volání/měsíc | zkušební klíč jen nekomerčně (škola OK) |
| **Z AI (GLM)** | nutný (z.ai) | modely *-Flash zdarma | čínská firma, data mimo EU |
| **NVIDIA NIM** | nutný (build.nvidia.com) | podle modelu | jen pro vývoj a testování |
| **Gonka Broker** | nutný + ověření telefonem | ~1 mil. tokenů/měsíc | |
| **OVHcloud AI Endpoints** | **není potřeba** | 2/min | francouzská firma, servery v EU |
| **Kilo Code** | **není potřeba** | 200/hod | automatický výběr může posílat dotazy k poskytovatelům, kteří je logují |
| **LLM7.io** | **není potřeba** (token zvedne limity) | 60/min s tokenem | nabídka modelů se často mění |

**Na vašem počítači / vlastní:**

| Poskytovatel | Klíč | Poznámka |
|---|---|---|
| **Ollama** | žádný | běží zdarma u vás (ollama.com), data nikam neodcházejí; jen lokálně, ne na online verzi |
| **Vlastní** | podle služby | jakákoli služba kompatibilní s OpenAI (zadáte adresu, např. `https://…/v1`) |

Ze seznamu jsme vynechali ModelScope a SiliconFlow (vyžadují čínské ověření totožnosti) a Aion Labs (zaměřený na hraní rolí).
Bezplatné služby jsou na výuku a vyzkoušení skvělé, ale mohou kdykoli změnit limity nebo skončit. Aplikace pak
jen přejde na pravidla.

**Jak na to:**
1. Vyberte **poskytovatele** v rozbalovacím seznamu.
2. Vložte **API klíč** (u OVHcloud, Kilo Code, LLM7 a Ollamy se nevyplňuje; u Cloudflare navíc Account ID).
   Pod výběrem se ukáže limit, jestli je klíč nutný, a upozornění k soukromí. Odkaz „kde ho získat“ vede na stránku s klíči.
3. Klikněte **Načíst modely**: aplikace se zeptá poskytovatele, jaké modely nabízí, a v poli **Model** je nabídne.
   Předvyplněný název je jen návrh, názvy modelů se často mění.
4. Klikněte **Vyzkoušet**: pošle se krátký zkušební dotaz a uvidíte, jestli AI odpověděla.
5. Klikněte **Uložit a používat**. V onboardingu pak u profilu uvidíte např. „Agent: Google Gemini (…)“.

Když AI selže (špatný klíč, došel kredit, výpadek), onboarding automaticky použije **pravidla**
a napíše proč. Odpověď AI se vždy kontroluje, takže nesmysl z modelu se do profilu nedostane.

**Soukromí:** do AI se posílají údaje o firmě (ARES, zakázky, text z webu firmy) a vaše odpovědi z dotazníku.
**Bezplatné tarify mohou dotazy ukládat nebo je použít ke zlepšování modelů**, proto tam nepište nic důvěrného
(aplikace to u každé bezplatné služby připomene). Nejsoukromější je Ollama, která běží jen u vás, z online
služeb pak placené tarify a OVHcloud se servery v EU.

### Další klíče

| Klíč | K čemu je | Kde ho získat | Cena |
|---|---|---|---|
| **Hlídač státu** | onboarding vidí smlouvy firmy za 3 roky | hlidacstatu.cz → registrace → API token | zdarma |
| **Exa** | export do Obsidianu dohledá zmínky o firmě na webu | dashboard.exa.ai | má bezplatný limit |

**Kam klíče vložit:**
- Na svém počítači: v záložce **Data** (uloží se do `config.local.json`, který se na GitHub nenahrává),
  nebo do souboru `.env` podle vzoru `.env.example`.
- Na online verzi: v Renderu u služby **Environment**. Pro AI: `LLM_POSKYTOVATEL` (`anthropic`, `openai`, `gemini`,
  `mistral`, `openrouter`, `vlastni`), klíč do příslušné proměnné (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
  `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`, u vlastního `LLM_API_KEY` a `LLM_URL`) a případně `LLM_MODEL`.
  Bezplatné služby: `GROQ_API_KEY`, `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`, `COHERE_API_KEY`, `ZAI_API_KEY`,
  `NVIDIA_API_KEY`, `GONKA_API_KEY`, `OVH_API_KEY`, `KILO_API_KEY`, `LLM7_API_KEY` (poslední tři nepovinné);
  `LLM_POSKYTOVATEL` pak `groq`, `openrouter_free`, `cloudflare`, `cohere`, `zai`, `nvidia`, `gonka`, `ovh`, `kilo`, `llm7`.
  Dále `HLIDAC_TOKEN`, `EXA_API_KEY`. Klíč zadaný v aplikaci by na Renderu po restartu zmizel.

**Klíče nikdy nenahrávejte na GitHub.** Soubor `config.json` v repozitáři má klíče prázdné a tak to musí zůstat.

---

## 8. Bezpečnost

Aplikace je postavená podle 11 pravidel z přednášky *Bezpečný vibe coding* (VŠE, 2026).
Podrobný popis je v [SECURITY.md](SECURITY.md), tady jen to hlavní srozumitelně:

**Co je chráněné a jak**

| Riziko | Co by se mohlo stát | Jak to aplikace řeší |
|---|---|---|
| Únik klíče | někdo by utrácel z vašeho účtu u AI | klíče nejsou nikdy na GitHubu ani v prohlížeči. Doma jsou v souboru `config.local.json`, na serveru v nastavení Renderu |
| Cizí člověk ovládá server | spustí stahování, změní klíče | online verze je pro návštěvníky jen ke čtení, správcovské akce chtějí heslo. Po 5 chybných pokusech se přihlašování na 15 minut zablokuje |
| Jeden návštěvník vidí data jiného | prozrazení plánů firmy z onboardingu | každý prohlížeč má vlastní oddělený prostor, cizí profil vrací „nenalezeno“ |
| Útok na peněženku | boti by volali placenou AI | návštěvníci bez hesla placená API nepoužívají, navíc platí denní strop (30 volání AI, 40× Exa) a limit požadavků za minutu |
| SQL injection a podvržené vstupy | únik nebo smazání dat | všechny dotazy do databáze jsou parametrizované, vstupy se kontrolují (IČO, délka textu, velikost požadavku) |
| Cizí stránka zneužije vaši aplikaci | podvržený požadavek z jiného webu | aplikace přijímá požadavky jen z vlastní stránky (kontrola `Origin` a `Host`, žádný CORS) |
| Server jako odrazový můstek | onboarding by stahoval adresy z vnitřní sítě | web firmy se stáhne jen z veřejné adresy, max. 1 MB |
| Chybové hlášky | prozrazení vnitřku aplikace | uživatel dostane obecnou hlášku s kódem, detail je jen v logu serveru |
| Zranitelné knihovny | známá díra v cizím kódu | jen 3 Python balíčky se zamčenými verzemi, automatická kontrola (pip-audit, npm audit) a Dependabot |

**Automatické kontroly na GitHubu.** Při každém nahrání kódu se v záložce **Actions** spustí
„Bezpečnost a testy“: 25 bezpečnostních testů (například jestli nepřihlášený nemůže měnit nastavení
nebo jestli jeden uživatel nevidí data druhého), kontrola zranitelných balíčků, bezpečnostní linter
a hledání uniklých klíčů (gitleaks) v celé historii. Zelená fajfka = v pořádku, červený křížek = něco je potřeba opravit.

**Co si zapnout na GitHubu (jednou, 10 minut)**

1. **Dvoufázové ověření (2FA):** vpravo nahoře profil → **Settings → Password and authentication →
   Enable two-factor authentication**. Nejlépe s aplikací (Google Authenticator, Microsoft Authenticator)
   nebo passkey, SMS až jako poslední možnost. **Záložní kódy (recovery codes) si uložte** na bezpečné místo.
2. **Hlídání zranitelností:** v repozitáři **Settings → Advanced Security** (případně *Code security*) zapněte
   **Dependency graph**, **Dependabot alerts** a **Dependabot security updates**.
3. **Hlídání klíčů:** tamtéž zapněte **Secret scanning** a **Push protection** (u veřejného repozitáře zdarma).
   GitHub pak zastaví nahrání, ve kterém by byl klíč.
4. **Kontrola kódu:** tamtéž **Code scanning → Set up → Default** (CodeQL, u veřejného repozitáře zdarma).
5. **Soukromé hlášení chyb:** tamtéž **Private vulnerability reporting → Enable** (na to odkazuje SECURITY.md).
6. **Ochrana hlavní větve:** **Settings → Branches → Add branch ruleset** pro `main`: zakázat
   *force push* a mazání větve, vyžadovat úspěšné kontroly „Bezpečnost a testy“.
7. **Token pro git s krátkou platností:** když vás git na počítači žádá o heslo, místo hesla použijte token.
   **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**:
   platnost 30 dní, **Repository access: Only select repositories** (jen tento repozitář), oprávnění
   **Contents: Read and write**, nic dalšího. Token nikdy nevkládejte do kódu ani do chatu s AI.
8. **Limit útrat u AI:** u poskytovatele, kterého používáte (console.anthropic.com, platform.openai.com,
   Google Cloud / AI Studio, console.mistral.ai, openrouter.ai), nastavte v části Billing / Limits měsíční limit
   (třeba 5 USD) a upozornění e-mailem. Klíč vytvořte jen pro TenderScope, ať ho jde kdykoli zrušit.

**Kdyby klíč přece jen unikl:** nejdřív ho u poskytovatele **zneplatněte** (vytvořte nový), pak zkontrolujte
spotřebu a teprve potom řešte historii gitu. Smazat klíč dalším commitem nestačí, v historii zůstává.

---

## 9. Časté otázky a problémy

**Po dvojkliku na TenderScope.bat se nic nestane nebo píše „python není rozpoznán“.**
Python není nainstalovaný, nebo jste nezaškrtli „Add python.exe to PATH“. Spusťte instalátor Pythonu znovu,
zvolte **Modify** a zaškrtněte to.

**Aktualizace dlouho „stojí“.**
Jeden měsíc dat má desítky MB a zpracování trvá 1–3 minuty. Průběh se vypisuje každých 5 sekund, takže je vidět, že pracuje.

**Registr smluv ukazuje 0.**
Rychlá aktualizace Registr smluv záměrně přeskakuje (je velký). Spusťte **Plnou aktualizaci**.

**Firma se nenajde.**
Firma možná ve stažených datech nemá žádnou zakázku. Zkuste IČO místo názvu, nebo stáhněte delší období (Plná aktualizace).

**Některá čísla nesedí.**
Data státu nejsou dokonalá (chybějící ceny, překlepy v hodnotách). Aplikace zjevné chyby vyřazuje a u čísel
píše, z čeho vychází. Pro dohledání použijte **Data → Diagnostika**.

**Online verze se dlouho načítá.**
Server po 15 minutách bez návštěvy usne. Počkejte asi minutu, pak už běží rychle.

---

## 10. Omezení

- Data jsou tak dobrá, jak je zadavatelé vyplnili. Starší zakázky často nemají obor (CPV) ani cenu.
- Úspěšnost (win rate) jde spočítat jen u soutěží, kde jsou zveřejnění i neúspěšní účastníci.
- Vzdálenost v dotazníku vhodnosti je odhad mezi městy po silnici, ne přesná trasa.
- Bezplatná online verze má málo paměti, proto má jen zmenšená data a Plnou aktualizaci je lepší dělat doma.
- Registr smluv obsahuje osobní údaje. Data používejte jen pro účely projektu.

---

## 11. Pro technicky zdatné

- **Backend:** Python 3.10+ (standardní knihovna, `requests`, `ijson`, `anthropic`), databáze SQLite.
  AI: Claude přes oficiální SDK, ostatní poskytovatelé přes standardní rozhraní `/chat/completions` (OpenAI-kompatibilní)
  pomocí `requests`, s JSON schématem a ústupem na jednodušší režim, když ho model nezná (`ts/llm.py`).
- **Frontend:** React 18 + TypeScript + Recharts, předkompilovaný ve `web/dist` (Node.js ke spuštění netřeba;
  úpravy: `cd web && npm install && npm run build`).
- **Architektura „agentů“:** Scout (stahování), Extractor (vytažení údajů ze záznamů), Verifier (kontrola, ověření
  v Registru smluv), Analyst (skóre), Briefer (zprávy), Recon a Onboarding agent (profil firmy).
- **Podobnost zakázek:** lokální TF-IDF nad názvy a CPV (bez externí vektorové databáze).

```bash
pip install -r requirements.txt
python server.py              # reálná data, http://127.0.0.1:8765
python server.py --demo       # umělá data bez internetu
```

**Proměnné prostředí pro server** (Docker / Render):

| Proměnná | Význam |
|---|---|
| `TS_ADMIN_HESLO` | heslo správce; bez něj je online verze jen ke čtení |
| `LLM_POSKYTOVATEL` | AI pro onboarding: `anthropic` (výchozí), `openai`, `mistral`, `openrouter`, zdarma `gemini`, `groq`, `openrouter_free`, `cloudflare`, `cohere`, `zai`, `nvidia`, `gonka`, `ovh`, `kilo`, `llm7`, dále `ollama`, `vlastni` |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`, `LLM_API_KEY` | klíč k vybrané AI |
| `LLM_MODEL`, `LLM_URL` | model a (u Ollamy / vlastního API) adresa |
| `HLIDAC_TOKEN`, `EXA_API_KEY` | nepovinné klíče |
| `TS_AUTO_AKTUALIZACE` | `rychle` (výchozí v Dockeru): při prázdné databázi stáhne data hned po startu |
| `TS_DEMO` | `1` = umělá data |
| `TS_LIMIT_LLM_DEN`, `TS_LIMIT_EXA_DEN` | denní strop volání placených API (výchozí 30 a 40) |
| `TS_LIMIT_ZA_MINUTU`, `TS_LIMIT_DRAHE_ZA_MINUTU` | rate limiting na IP adresu (výchozí 120 a 10) |
| `TS_POVOLENE_HOSTY` | nepovinné: seznam domén, na kterých smí aplikace odpovídat |
| `PORT`, `TS_HOST` | port a adresa serveru (v Dockeru `0.0.0.0`) |

Soubory pro nasazení: `Dockerfile`, `render.yaml`, `pripravit_db.py`. Podrobný návod je v [NAVOD.md](NAVOD.md).

Testy: `python -m unittest discover -s tests -v`. Pravidla pro AI asistenty: [AGENTS.md](AGENTS.md).
Bezpečnost: [SECURITY.md](SECURITY.md).
