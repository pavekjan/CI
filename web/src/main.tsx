import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, type Stav } from "./api";
import { SearchBox } from "./components";
import Data from "./pages/Data";
import Firma from "./pages/Firma";
import Home from "./pages/Home";
import Onboarding from "./pages/Onboarding";
import TrhPage from "./pages/TrhPage";
import "./styles.css";

function useHash() {
  const [h, setH] = useState(window.location.hash.slice(1) || "/");
  useEffect(() => {
    const on = () => setH(window.location.hash.slice(1) || "/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return h;
}

const IKONY: Record<string, JSX.Element> = {
  firmy: <path d="M4 20V8l6-4 6 4v12M10 20v-5h0M16 10h4v10H4" />,
  onboarding: <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" /></>,
  trh: <path d="M4 19h16M7 15v-4M12 15V7M17 15v-6" />,
  data: <><ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" /></>,
};
const Ikona = ({ n }: { n: string }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{IKONY[n]}</svg>
);

function useTema() {
  const [tema, setTema] = useState<string | null>(() => { try { return localStorage.getItem("tema"); } catch { return null; } });
  useEffect(() => {
    if (tema) document.documentElement.setAttribute("data-theme", tema); else document.documentElement.removeAttribute("data-theme");
    try { if (tema) localStorage.setItem("tema", tema); else localStorage.removeItem("tema"); } catch { /* bez uloziste */ }
  }, [tema]);
  const tmava = tema ? tema === "dark" : window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  return { tmava, prepni: () => setTema(tmava ? "light" : "dark") };
}

function App() {
  const { tmava, prepni } = useTema();
  const route = useHash();
  const [stav, setStav] = useState<Stav | null>(null);
  const refresh = useCallback(() => {
    api.stav().then(setStav).catch(() => setStav(null));
  }, []);
  useEffect(refresh, [refresh]);

  const parts = route.split("/").filter(Boolean);
  let page;
  if (parts[0] === "firma" && parts[1]) page = <Firma ico={decodeURIComponent(parts[1])} prazdnaDb={stav ? stav.zakazek === 0 : false} />;
  else if (parts[0] === "trh") page = <TrhPage segment={parts[1] ? decodeURIComponent(parts[1]) : null} />;
  else if (parts[0] === "onboarding") page = <Onboarding ico={parts[1] ? decodeURIComponent(parts[1]) : null} />;
  else if (parts[0] === "data") page = <Data stav={stav} refresh={refresh} />;
  else page = <Home stav={stav} />;

  const active = (p: string) => (parts[0] ?? "") === p ? "active" : "";

  return (
    <>
      <header className="topbar">
        <a className="brand" href="#/">
          <span className="brand-mark">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m20 20-4.5-4.5" /></svg>
          </span>
          TenderScope
        </a>
        <nav className="nav">
          <a className={active("") || active("firma")} href="#/"><Ikona n="firmy" />Firmy</a>
          <a className={active("onboarding")} href="#/onboarding"><Ikona n="onboarding" />Onboarding</a>
          <a className={active("trh")} href="#/trh"><Ikona n="trh" />Trh</a>
          <a className={active("data")} href="#/data"><Ikona n="data" />Data</a>
        </nav>
        <div className="spacer" />
        {stav?.demo && <span className="badge demo">DEMO data – vymyšlené firmy</span>}
        {parts[0] && <div style={{ width: 280, maxWidth: "100%" }}><SearchBox compact /></div>}
        <button className="iconbtn" onClick={prepni} title={tmava ? "Světlý režim" : "Tmavý režim"} aria-label="Přepnout světlý / tmavý režim">
          {tmava
            ? <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
            : <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>}
        </button>
      </header>
      <main>{page}</main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
