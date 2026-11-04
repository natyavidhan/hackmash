import { Link } from "react-router-dom";
import { useCatalog } from "../lib/catalog";
import { CURRENCIES } from "../lib/format";
import { currencyPref, tracker, useStore } from "../lib/tracker";

export function Footer() {
  const { catalog } = useCatalog();
  const store = useStore();
  const platforms = catalog?.sources.filter((s) => s.count > 0).length ?? 0;
  return (
    <footer className="site-footer">
      <div className="site-footer__inner">
        <p className="site-footer__note">
          Hackmash pins every public hackathon it can find on {platforms || "a dozen"} platforms, refreshed every few hours.
          Applying always happens on the original platform. Your tabs, notes and hidden notices stay in this browser and
          are never uploaded.
        </p>
        <div className="site-footer__links">
          <Link to="/sources">Where the data comes from</Link>
          <a href="/api/docs">Public API</a>
          <a href="https://github.com/natyavidhan/hackmash" target="_blank" rel="noopener noreferrer">
            Source code
          </a>
          <label className="site-footer__currency">
            Show prizes in
            <select
              className="field field--inline"
              value={currencyPref(store)}
              onChange={(e) => tracker.setCurrency(e.target.value)}
            >
              {CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
    </footer>
  );
}
