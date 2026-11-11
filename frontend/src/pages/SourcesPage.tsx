import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";
import { useCatalog, useNow } from "../lib/catalog";
import { plural, relativeAgo } from "../lib/format";

export function SourcesPage() {
  const { catalog, state, items } = useCatalog();
  const now = useNow();
  const sources = [...(catalog?.sources ?? [])].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  const india = sources.filter((s) => s.region === "india");
  const global = sources.filter((s) => s.region !== "india");
  const merged = items.filter((h) => (h.also_on ?? []).length > 0).length;

  const table = (list: typeof sources, title: string) => (
    <section className="sources__group">
      <h2 className="sources__heading">{title}</h2>
      <div className="register paper">
        <table className="register__table sources__table">
          <thead>
            <tr>
              <th scope="col">Platform</th>
              <th scope="col">Known for</th>
              <th scope="col" className="num">
                On the board
              </th>
              <th scope="col">Last checked</th>
            </tr>
          </thead>
          <tbody>
            {list.map((s) => (
              <tr key={s.key}>
                <td className="sources__name">
                  {s.homepage ? (
                    <a href={s.homepage} target="_blank" rel="noopener noreferrer">
                      {s.name} <ArrowUpRight size={13} aria-hidden="true" />
                    </a>
                  ) : (
                    s.name
                  )}
                  <span className="register__sub">{s.focus}</span>
                </td>
                <td className="sources__desc">{s.description}</td>
                <td className="num">
                  <Link to={`/?source=${s.key}`}>{s.count.toLocaleString("en-IN")}</Link>
                </td>
                <td className="sources__health">
                  <span className={`health health--${s.ok ? "ok" : s.last_ok_at ? "stale" : "down"}`} aria-hidden="true" />
                  {s.last_ok_at ? relativeAgo(Date.parse(s.last_ok_at), now) : "not yet"}
                  {!s.ok && s.error && <span className="register__sub">Last attempt failed; showing the previous listings.</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );

  return (
    <main id="main" className="page sources">
      <h1 className="page-title">Where the notices come from</h1>
      <p className="page-lede">
        Hackmash reads the public listings of {plural(sources.length, "platform")} every few hours, puts every event into one format (your timezone,
        one currency, the same fields) and merges events listed on more than one platform
        {merged ? ` (${plural(merged, "event")} right now)` : ""}. Nothing here is hosted by Hackmash: registration, rules and prizes always live on
        the original platform.
      </p>
      {state === "loading" && <p className="page-lede">Loading the source list…</p>}
      {india.length > 0 && table(india, "India")}
      {global.length > 0 && table(global, "Global")}

      <section className="sources__notes paper">
        <h2>How listings are read</h2>
        <ul>
          <li>Only public pages and public APIs are read, at a polite rate, a few times a day.</li>
          <li>Dates are converted to your timezone. Prize pools are converted to your chosen currency at the day’s exchange rate, so treat them as approximate.</li>
          <li>Fields a platform does not publish stay blank rather than guessed. Paid entry and invite-only events are flagged.</li>
          <li>When a platform stops listing an event, it disappears from the board after a day and a half, but stays in your tabs.</li>
          <li>
            Missing a platform or spotted a wrong listing?{" "}
            <a href="https://github.com/natyavidhan/hackmash/issues" target="_blank" rel="noopener noreferrer">
              Open an issue
            </a>
            . Developers can use the same data from the <a href="https://github.com/natyavidhan/hackmash#api">public API</a>.
          </li>
        </ul>
      </section>
    </main>
  );
}
