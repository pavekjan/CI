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

function App() {
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
          <a className={active("")} href="#/">Firmy</a>
          <a className={active("onboarding")} href="#/onboarding">Onboarding</a>
          <a className={active("trh")} href="#/trh">Trh</a>
          <a className={active("data")} href="#/data">Data</a>
        </nav>
        <div className="spacer" />
        {stav?.demo && <span className="badge demo">DEMO data – vymyšlené firmy</span>}
        {parts[0] && <div style={{ width: 280, maxWidth: "100%" }}><SearchBox compact /></div>}
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
