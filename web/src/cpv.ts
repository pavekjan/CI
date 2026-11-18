/** Oddily CPV (evropsky ciselnik predmetu verejnych zakazek) - aby uzivatel nevidel jen cisla. Shodne s ts/api.py CPV_DIV. */
export const CPV_DIV: Record<string, string> = {
  "03": "Zemědělské a lesnické produkty", "09": "Paliva a energie", "14": "Těžba a kovy", "15": "Potraviny a nápoje",
  "16": "Zemědělské stroje", "18": "Oděvy a obuv", "19": "Kůže, textil, plasty", "22": "Tiskoviny", "24": "Chemické výrobky",
  "30": "Kancelářská a výpočetní technika", "31": "Elektrické stroje a přístroje", "32": "Komunikační a AV zařízení",
  "33": "Zdravotnické přístroje a léčiva", "34": "Dopravní prostředky", "35": "Bezpečnostní a obranné vybavení",
  "37": "Sport, hry, hudební nástroje", "38": "Laboratorní a optické přístroje", "39": "Nábytek a vybavení",
  "41": "Voda", "42": "Průmyslové stroje", "43": "Důlní a stavební stroje", "44": "Stavební konstrukce a materiály",
  "45": "Stavební práce", "48": "Software a informační systémy", "50": "Opravy a údržba", "51": "Instalace",
  "55": "Hotelové a stravovací služby", "60": "Dopravní služby", "63": "Podpůrné dopravní služby",
  "64": "Pošta a telekomunikace", "65": "Veřejné služby (energie, voda)", "66": "Finanční a pojišťovací služby",
  "70": "Realitní služby", "71": "Architektonické a inženýrské služby", "72": "IT služby", "73": "Výzkum a vývoj",
  "75": "Veřejná správa a obrana", "76": "Služby pro těžbu ropy a plynu", "77": "Zemědělské a zahradnické služby",
  "79": "Obchodní služby (právo, marketing, HR)", "80": "Vzdělávání", "85": "Zdravotní a sociální služby",
  "90": "Odpady, úklid, životní prostředí", "92": "Kultura, sport, rekreace", "98": "Ostatní služby",
};

export const oborKodu = (c: string) => CPV_DIV[c.slice(0, 2)] ?? "jiný obor";

export const CPV_VYSVETLENI = "CPV = evropský číselník předmětů veřejných zakázek. Každá zakázka má osmimístný kód, první dvě číslice určují obor (např. 15… = potraviny, 30… = počítače, 45… = stavby).";

/** Zkratky zdroju -> srozumitelny nazev + vysvetleni do tooltipu */
const ZDROJE: [RegExp, string, string][] = [
  [/ISVZ/g, "registr zakázek", "ISVZ – Informační systém o veřejných zakázkách: oficiální data státu o soutěžích (NEN, Věstník veřejných zakázek)."],
  [/ARES/g, "ARES", "ARES – Administrativní registr ekonomických subjektů: státní rejstřík firem (název, sídlo, činnosti)."],
];

export function zdrojLidsky(z: string): { text: string; title: string } {
  let text = z;
  const title: string[] = [];
  for (const [re, nahrada, vysvetleni] of ZDROJE) {
    if (re.test(text)) {
      text = text.replace(re, nahrada);
      title.push(vysvetleni);
    }
    re.lastIndex = 0;
  }
  return { text, title: title.join(" ") };
}
