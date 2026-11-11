import { Link, NavLink } from "react-router-dom";
import { useCatalog, useNow } from "../lib/catalog";
import { relativeAgo } from "../lib/format";
import { useStore } from "../lib/tracker";

export function Header() {
  const { generatedAt, catalog } = useCatalog();
  const store = useStore();
  const now = useNow();
  const active = Object.values(store.items).filter((t) => t.status !== "withdrawn").length;
  const platforms = catalog?.sources.filter((s) => s.count > 0).length ?? 0;

  return (
    <header className="frame">
      <div className="frame__inner">
        <Link to="/" className="wordmark" aria-label="Hackmash, back to the board">
          <span className="pin pin--red wordmark__pin" aria-hidden="true" />
          <span className="wordmark__text">Hackmash</span>
        </Link>
        <nav className="frame__nav" aria-label="Main">
          <NavLink to="/" end className="frame__link">
            Board
          </NavLink>
          <NavLink to="/tracker" className="frame__link">
            My tabs
            {active > 0 && (
              <span className="frame__count" aria-label={`${active} tracked`}>
                {active}
              </span>
            )}
          </NavLink>
          <NavLink to="/sources" className="frame__link frame__link--wide">
            Sources
          </NavLink>
        </nav>
        {generatedAt && (
          <p className="frame__meta">
            <span className={`frame__dot${now - generatedAt > 12 * 3_600_000 ? " frame__dot--stale" : ""}`} aria-hidden="true" />
            {platforms} platforms, updated {relativeAgo(generatedAt, now)}
          </p>
        )}
      </div>
    </header>
  );
}
