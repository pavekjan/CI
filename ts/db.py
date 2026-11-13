"""SQLite databaze - spolecna pamet vsech agentu."""
import os
import sqlite3

from .util import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS zakazky (
    id TEXT PRIMARY KEY,
    zdroj TEXT,
    nazev TEXT,
    zadavatel_ico TEXT,
    zadavatel_nazev TEXT,
    cpv TEXT,
    cpv_hlavni TEXT,
    druh TEXT,
    postup TEXT,
    rezim TEXT,
    stav TEXT,
    nuts TEXT,
    kraj TEXT,
    predpokladana_hodnota REAL,
    datum_zahajeni TEXT,
    lhuta_nabidek TEXT,
    pocet_nabidek INTEGER,
    kriteria TEXT,
    url TEXT,
    relevance TEXT,
    stazeno TEXT
);
CREATE TABLE IF NOT EXISTS vitezove (
    zakazka_id TEXT,
    dodavatel_ico TEXT,
    dodavatel_nazev TEXT,
    cena_bez_dph REAL,
    overeno_rs INTEGER DEFAULT 0,
    smlouva_id TEXT,
    PRIMARY KEY (zakazka_id, dodavatel_ico, dodavatel_nazev)
);
CREATE TABLE IF NOT EXISTS ucastnici (
    zakazka_id TEXT,
    dodavatel_ico TEXT,
    dodavatel_nazev TEXT,
    nabidkova_cena REAL,
    PRIMARY KEY (zakazka_id, dodavatel_ico, dodavatel_nazev)
);
CREATE TABLE IF NOT EXISTS smlouvy (
    id TEXT PRIMARY KEY,
    predmet TEXT,
    datum_uzavreni TEXT,
    hodnota_bez_dph REAL,
    hodnota_s_dph REAL,
    zadavatel_ico TEXT,
    zadavatel_nazev TEXT,
    url TEXT
);
CREATE TABLE IF NOT EXISTS smlouvy_strany (
    smlouva_id TEXT,
    ico TEXT,
    nazev TEXT
);
CREATE INDEX IF NOT EXISTS ix_strany_ico ON smlouvy_strany(ico);
-- Registr smluv za dlouhe obdobi jen jako souhrn (cele smlouvy by se na bezplatny server nevesly).
-- dump = mesicni soubor registru (napr. 2025_03); pri novem zpracovani se jeho radky nahradi.
CREATE TABLE IF NOT EXISTS smlouvy_souhrn (ico TEXT, mesic TEXT, dump TEXT, pocet INTEGER, hodnota REAL, PRIMARY KEY (ico, mesic, dump));
CREATE TABLE IF NOT EXISTS smlouvy_odberatele (ico TEXT, zadavatel_ico TEXT, dump TEXT, pocet INTEGER, hodnota REAL,
    PRIMARY KEY (ico, zadavatel_ico, dump));
CREATE TABLE IF NOT EXISTS subjekty (ico TEXT PRIMARY KEY, nazev TEXT);
CREATE INDEX IF NOT EXISTS ix_rss_dump ON smlouvy_souhrn(dump);
CREATE INDEX IF NOT EXISTS ix_rso_dump ON smlouvy_odberatele(dump);
CREATE INDEX IF NOT EXISTS ix_vit_ico ON vitezove(dodavatel_ico);
CREATE INDEX IF NOT EXISTS ix_uc_ico ON ucastnici(dodavatel_ico);
CREATE INDEX IF NOT EXISTS ix_uc_zak ON ucastnici(zakazka_id);
CREATE INDEX IF NOT EXISTS ix_vit_zak ON vitezove(zakazka_id);
CREATE INDEX IF NOT EXISTS ix_zak_zad ON zakazky(zadavatel_ico);
CREATE INDEX IF NOT EXISTS ix_zak_cpv ON zakazky(cpv_hlavni);
CREATE TABLE IF NOT EXISTS dodavatele (
    ico TEXT PRIMARY KEY,
    nazev TEXT,
    nazev_norm TEXT,
    vyhry INTEGER,
    ucasti INTEGER,
    objem REAL,
    smluv_rs INTEGER,
    ucasti_zname INTEGER,
    vyhry_zname INTEGER
);
CREATE INDEX IF NOT EXISTS ix_smlouvy_zad ON smlouvy(zadavatel_ico);
CREATE TABLE IF NOT EXISTS firmy (
    ico TEXT PRIMARY KEY,
    nazev TEXT,
    sidlo TEXT,
    kraj TEXT,
    nace TEXT,
    pravni_forma TEXT,
    datum_vzniku TEXT,
    datum_zaniku TEXT,
    stazeno TEXT
);
CREATE TABLE IF NOT EXISTS zpravy (
    url TEXT PRIMARY KEY,
    titulek TEXT,
    zdroj TEXT,
    datum TEXT,
    dotaz TEXT
);
CREATE TABLE IF NOT EXISTS priznaky (
    objekt_typ TEXT,
    objekt_id TEXT,
    typ TEXT,
    popis TEXT
);
CREATE TABLE IF NOT EXISTS soubory (
    klic TEXT PRIMARY KEY,
    podpis TEXT
);
CREATE TABLE IF NOT EXISTS behy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zacatek TEXT,
    konec TEXT,
    krok TEXT,
    stav TEXT,
    poznamka TEXT
);
"""


def connect(path=None):
    path = path or os.path.join(DATA_DIR, "tenderscope.db")
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")  # aplikace muze cist, zatimco agenti zapisuji
    con.executescript(SCHEMA)
    sloupce = {r[1] for r in con.execute("PRAGMA table_info(zakazky)")}
    for sl in ("kvalifikace TEXT", "min_obrat REAL"):  # podminky ucasti, pokud je zdroj uvadi (extractor)
        if sl.split()[0] not in sloupce:
            con.execute(f"ALTER TABLE zakazky ADD COLUMN {sl}")  # nosec B608 - konstanta z kodu
    if "cpv_odhad" not in sloupce:  # odhad segmentu u zakazek bez CPV ("slova" / "ai"), viz ts/segmenty.py
        con.execute("ALTER TABLE zakazky ADD COLUMN cpv_odhad TEXT")
        con.commit()
    return con
