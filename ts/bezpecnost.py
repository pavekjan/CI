"""Bezpecnostni pomucky serveru (podle prednasky "Bezpecny vibe coding", pravidla 1-11).

- validace vstupu (IČO, texty, URL webu) - pravidlo 3
- ochrana proti SSRF: server nestahuje adresy z vnitrni site - pravidlo 3/9
- rate limiting a denni limity placenych API (Claude, Exa) - pravidlo 7/10
- identita anonymniho uzivatele (vlastnictvi onboardingu) - pravidlo 2
- CSV bez formuli pro Excel - pravidlo 3
Vse jen standardni knihovna, zadne nove balicky (pravidlo 4).
"""
import hashlib
import ipaddress
import re
import socket
import threading
import time
from collections import defaultdict, deque
from datetime import date
from urllib.parse import urljoin, urlparse


class ChybaVstupu(ValueError):
    """Chyba, jejiz text je bezpecne ukazat uzivateli (HTTP 400)."""


# ------------------------------------------------------------------ validace vstupu
ICO_RE = re.compile(r"^\d{1,8}$")


def ico(v, pole="IČO"):
    s = re.sub(r"\s", "", str(v or ""))
    if not ICO_RE.match(s):
        raise ChybaVstupu(f"{pole} musí být číslo s nejvýš 8 číslicemi.")
    return s.zfill(8)


def text(v, max_delka, pole="text", povinne=False):
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ChybaVstupu(f"Pole {pole} musí být text.")
    v = v.strip()
    if povinne and not v:
        raise ChybaVstupu(f"Pole {pole} je povinné.")
    if len(v) > max_delka:
        raise ChybaVstupu(f"Pole {pole} je moc dlouhé (max. {max_delka} znaků).")
    if any(ord(c) < 32 and c not in "\t\n\r" for c in v):
        raise ChybaVstupu(f"Pole {pole} obsahuje nepovolené znaky.")
    return v


def klic_api(v, pole):
    v = text(v, 300, pole)
    if v and not re.fullmatch(r"[A-Za-z0-9_\-.:]+", v):
        raise ChybaVstupu(f"{pole} má neplatný formát.")
    return v


def model(v):
    v = text(v, 120, "model")
    if v and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@\-]{0,119}", v):
        raise ChybaVstupu("Neplatný název modelu (jen písmena, čísla a . _ : / @ -).")
    return v


def over_api_url(url, verejne):
    """Adresa AI API (Ollama / vlastni). Nastavuje ji jen spravce.
    Lokalne smi byt i http://localhost (Ollama na vasem pocitaci). Na verejnem serveru jen https na verejnou
    adresu, aby se nastaveni nedalo zneuzit k pristupu do vnitrni site serveru (SSRF)."""
    url = text(url, 300, "adresa API").rstrip("/")
    if not url:
        return ""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ChybaVstupu("Adresa API musí být např. https://api.example.com/v1")
    if not verejne:
        return url
    if u.scheme != "https":
        raise ChybaVstupu("Na online verzi musí adresa API začínat https://")
    try:
        adresy = {i[4][0] for i in socket.getaddrinfo(u.hostname, u.port or 443)}
    except (socket.gaierror, UnicodeError):
        raise ChybaVstupu("Adresu API se nepodařilo najít.")
    if not adresy or not all(_verejna_ip(a) for a in adresy):
        raise ChybaVstupu("Na online verzi musí adresa API vést na veřejný server.")
    return url


def odpovedi(v):
    """Odpovedi z dotazniku onboardingu: {id: {"vybrano": [str], "text": str}}."""
    if not isinstance(v, dict) or len(v) > 20:
        raise ChybaVstupu("Neplatné odpovědi.")
    out = {}
    for k, o in v.items():
        k = text(k, 40, "id otázky")
        if not isinstance(o, dict):
            raise ChybaVstupu("Neplatné odpovědi.")
        vyb = o.get("vybrano") or []
        if not isinstance(vyb, list) or len(vyb) > 30:
            raise ChybaVstupu("Neplatné odpovědi.")
        out[k] = {"vybrano": [text(x, 300, "odpověď") for x in vyb], "text": text(o.get("text"), 2000, "odpověď")}
    return out


# ------------------------------------------------------------------ SSRF: jen verejne adresy
def _verejna_ip(ip):
    a = ipaddress.ip_address(ip)
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_global and not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast
                                or a.is_reserved or a.is_unspecified)


def over_url(url):
    """Vrati normalizovanou URL, nebo vyhodi ChybaVstupu. Povoli jen http(s) na verejne IP adresy,
    aby se pres onboarding nedalo sahat na vnitrni sit serveru (metadata cloudu, localhost...)."""
    url = text(url, 300, "web")
    if not url:
        return None
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    u = urlparse(url)
    if u.scheme.lower() not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ChybaVstupu("Web musí být běžná adresa, např. https://www.firma.cz")
    if u.port not in (None, 80, 443):
        raise ChybaVstupu("Web musí používat standardní port (80 nebo 443).")
    try:
        adresy = {i[4][0] for i in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))}
    except (socket.gaierror, UnicodeError):
        raise ChybaVstupu("Adresu webu se nepodařilo najít.")
    if not adresy or not all(_verejna_ip(a) for a in adresy):
        raise ChybaVstupu("Tahle adresa nevede na veřejný web.")
    return url


def stahni_web(url, session, max_bajtu=1_000_000, max_presmerovani=3, timeout=10):
    """Bezpecne stazeni stranky: kazde presmerovani se znovu kontroluje a cte se max. 1 MB."""
    for _ in range(max_presmerovani + 1):
        url = over_url(url)
        r = session.get(url, timeout=timeout, allow_redirects=False, stream=True)
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            dalsi = r.headers.get("Location")
            r.close()
            if not dalsi:
                break
            url = urljoin(url, dalsi)
            continue
        data = b""
        for kus in r.iter_content(65536):
            data += kus
            if len(data) > max_bajtu:
                break
        r.close()
        return r.status_code, data[:max_bajtu].decode(r.encoding or "utf-8", "replace"), url
    raise ChybaVstupu("Web přesměrovává příliš mnohokrát.")


# ------------------------------------------------------------------ rate limiting
class RateLimiter:
    """Klouzave okno: max. `limit` pozadavku za `okno` sekund na jeden klic (IP adresu)."""

    def __init__(self, limit, okno):
        self.limit, self.okno = limit, okno
        self._z = defaultdict(deque)
        self._lock = threading.Lock()

    def _okno(self, klic, ted):
        q = self._z[klic]
        while q and q[0] <= ted - self.okno:
            q.popleft()
        return q

    def vycerpano(self, klic):
        """Jen zjisti, jestli je limit vycerpany (nic nezapocita)."""
        with self._lock:
            return len(self._okno(klic, time.monotonic())) >= self.limit

    def zapocitej(self, klic):
        with self._lock:
            self._okno(klic, time.monotonic()).append(time.monotonic())

    def povol(self, klic):
        ted = time.monotonic()
        with self._lock:
            q = self._okno(klic, ted)
            if len(q) >= self.limit:
                return False
            q.append(ted)
            if len(self._z) > 10000:  # ochrana pameti
                for k in [k for k, v in self._z.items() if not v][:5000]:
                    del self._z[k]
            return True


class DenniLimit:
    """Strop poctu volani placeneho API za den (pro celou aplikaci). Chrani penezenku."""

    def __init__(self, limit):
        self.limit = limit
        self._den, self._n = None, 0
        self._lock = threading.Lock()

    def vezmi(self):
        with self._lock:
            dnes = date.today()
            if self._den != dnes:
                self._den, self._n = dnes, 0
            if self.limit <= 0 or self._n >= self.limit:
                return False
            self._n += 1
            return True

    @property
    def pouzito(self):
        return self._n if self._den == date.today() else 0


# ------------------------------------------------------------------ identita anonymniho uzivatele
UZIVATEL_RE = re.compile(r"^[A-Za-z0-9\-]{16,64}$")


def vlastnik_z_hlavicky(h):
    """Prohlizec si vygeneruje nahodne ID (crypto.randomUUID) a posila ho v hlavicce X-Uzivatel.
    Server si uklada jen jeho hash. Kdo ID nezna, cizi onboarding neuvidi (vrati se 'nenalezeno')."""
    if not h or not UZIVATEL_RE.match(h):
        raise ChybaVstupu("Chybí identifikace prohlížeče. Obnovte stránku.")
    return "u:" + hashlib.sha256(h.encode()).hexdigest()[:32]


# ------------------------------------------------------------------ CSV bez formuli
def bunka_csv(x):
    """Excel spousti bunky zacinajici = + - @ jako vzorec (CSV injection). Pridame apostrof."""
    if isinstance(x, str) and x[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + x
    return x
