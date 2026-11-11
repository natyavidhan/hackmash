import { ArrowRight, Globe, MapPinOff, Minus, Plus, Shrink, Wifi, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent, type ReactNode } from "react";
import geo from "../assets/india-map.json";
import { plural, prizeParts } from "../lib/format";
import { DAY, nextDeadline } from "../lib/lifecycle";
import {
  clusterPins,
  groupByCity,
  groupPlaces,
  handLoop,
  overlaps,
  pinStack,
  placeTags,
  STACK_OFFSETS,
  type Box,
  type Place,
  type PlacedPin,
} from "../lib/mapClusters";
import { useMediaQuery } from "../lib/media";
import { makeProjection } from "../lib/projection";
import type { Tracked } from "../lib/tracker";
import type { Hackathon } from "../lib/types";
import { DeadlineStamp, OpenNoticeLink, pinFor, TimeLeft } from "./NoticeParts";
import "../styles/map.css";

const W = geo.width;
const H = geo.height;
const MAX_ZOOM = 8;
const project = makeProjection(geo.projection);
const km = (d: number) => project(77.2, 28.6)[1] - project(77.2, 28.6 + d / 111.2)[1]; // map units, measured from Delhi
const REACH = km(50); // towns this close to a city are part of its place ("Delhi NCR")
const NOWHERE = "nowhere"; // the pick for in-person events that don't say where
const PAPER = "#fdfcf8"; // --paper: SVG attributes can't read CSS variables
// lines around the coast, printed-atlas style: [stroke width px, colour], outermost first
const WATER: [number, string][] = [
  [19, "rgb(29 23 18 / 0.08)"],
  [17, PAPER],
  [12, "rgb(29 23 18 / 0.13)"],
  [10, PAPER],
  [6, "rgb(29 23 18 / 0.2)"],
  [4, PAPER],
];

interface Props {
  items: Hackathon[];
  now: number;
  tracked: Record<string, Tracked>;
  currency: string;
  fx?: Record<string, number>;
  /** put these cities' notices on the board */
  onShowCities: (cities: string[]) => void;
  onShowOnline: () => void;
  onShowAbroad: (countries: string[]) => void;
}

interface Camera {
  z: number;
  cx: number;
  cy: number;
}
const WHOLE: Camera = { z: 1, cx: W / 2, cy: H / 2 };

function clamp(c: Camera): Camera {
  const z = Math.min(MAX_ZOOM, Math.max(1, c.z));
  const hw = W / (2 * z);
  const hh = H / (2 * z);
  return { z, cx: Math.min(W - hw, Math.max(hw, c.cx)), cy: Math.min(H - hh, Math.max(hh, c.cy)) };
}

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The camera eases to where it's sent (220 ms), except while a drag moves it. */
function useCamera() {
  const [goal, setGoal] = useState({ cam: WHOLE, instant: true });
  const [shown, setShown] = useState(WHOLE);
  const current = useRef(WHOLE);
  useEffect(() => {
    const to = goal.cam;
    if (goal.instant || reducedMotion()) {
      current.current = to;
      setShown(to);
      return;
    }
    const from = current.current;
    const t0 = performance.now();
    let raf = 0;
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / 220);
      const e = 1 - Math.pow(1 - p, 3);
      const c = { z: from.z * Math.pow(to.z / from.z, e), cx: from.cx + (to.cx - from.cx) * e, cy: from.cy + (to.cy - from.cy) * e };
      current.current = c;
      setShown(c);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [goal]);
  const go = useCallback((cam: Camera, instant = false) => setGoal({ cam: clamp(cam), instant }), []);
  return { goal: goal.cam, shown, go };
}

const byDeadline = (now: number) => (a: Hackathon, b: Hackathon) =>
  (nextDeadline(a, now)?.at ?? Infinity) - (nextDeadline(b, now)?.at ?? Infinity) || a.title.localeCompare(b.title);

/** Registrations and submissions that close within a week (a start date isn't closing). */
function closingThisWeek(items: Hackathon[], now: number): number {
  return items.filter((h) => {
    const nd = nextDeadline(h, now);
    return !!nd && nd.kind !== "start" && nd.at - now < 7 * DAY;
  }).length;
}

export default function MapView({ items, now, tracked, currency, fx, onShowCities, onShowOnline, onShowAbroad }: Props) {
  const wide = useMediaQuery("(min-width: 1021px)");

  // what the map can show, and what it has to admit it can't
  const { placed, online, abroad, nowhere } = useMemo(() => {
    const placed: Hackathon[] = [];
    const abroad: Hackathon[] = [];
    const nowhere: Hackathon[] = [];
    let online = 0;
    for (const h of items) {
      if (h.mode === "online") online++;
      else if (!h.mode) continue; // the platform didn't say: not on the map, not counted as missing
      else if (h.country && h.country !== "India") abroad.push(h);
      else if (h.lat !== undefined && h.lng !== undefined) placed.push(h);
      else nowhere.push(h);
    }
    return { placed, online, abroad, nowhere };
  }, [items]);
  const abroadCountries = useMemo(() => [...new Set(abroad.map((h) => h.country!))], [abroad]);
  const places = useMemo(() => groupPlaces(groupByCity(placed, project), REACH), [placed]);

  // the map box keeps the whole country's proportions at every zoom
  const boxRef = useRef<HTMLDivElement>(null);
  const [boxW, setBoxW] = useState(0);
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBoxW(el.clientWidth));
    ro.observe(el);
    setBoxW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const boxH = (boxW * H) / W;

  const { goal, shown, go } = useCamera();
  const vw = W / shown.z;
  const vh = H / shown.z;
  const vx = shown.cx - vw / 2;
  const vy = shown.cy - vh / 2;
  const k = boxW / vw; // px per map unit, as drawn now
  const kGoal = (boxW * goal.z) / W; // ... once the camera arrives
  const small = boxW < 480;
  // places too close to tell apart at this zoom share a pin
  const pins = useMemo(() => (kGoal ? clusterPins(places, (small ? 17 : 19) / kGoal) : []), [places, kGoal, small]);

  // The pick is a place (or the events that give no place), never a pin: what's
  // circled, what's listed and the list of places agree at every zoom and width.
  const [pick, setPick] = useState<string | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const picked = pick && pick !== NOWHERE ? places.find((p) => p.key === pick) : undefined;
  const pickedPin = picked ? pins.find((pin) => pin.places.includes(picked)) : undefined;
  const pickedItems = useMemo(
    () => (pick === NOWHERE ? [...nowhere] : picked ? [...picked.items] : []).sort(byDeadline(now)),
    [pick, picked, nowhere, now],
  );
  useEffect(() => {
    if (pick && !pickedItems.length) setPick(null); // the filters took everything there away
  }, [pick, pickedItems.length]);

  const close = useCallback(() => {
    const pinButton = pickedPin && boxRef.current?.querySelector<HTMLElement>(`.mpin[data-key="${CSS.escape(pickedPin.key)}"]`);
    const back = opener.current?.isConnected ? opener.current : pinButton;
    setPick(null);
    // keyboard users carry on from the pin or row that opened it
    requestAnimationFrame(() => back?.focus({ preventScroll: true }));
  }, [pickedPin]);
  useEffect(() => {
    if (!pick) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !document.querySelector("dialog[open]") && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pick, close]);

  const choose = (key: string, from: HTMLElement | null, keepOpener = false) => {
    if (key === pick) return close();
    if (!keepOpener) opener.current = from;
    setPick(key);
    // on a phone the notices come up from the bottom: bring the place into the half that stays visible
    const place = places.find((p) => p.key === key);
    if (wide || !place || !boxRef.current) return;
    const top = window.scrollY + boxRef.current.getBoundingClientRect().top + (place.y - vy) * k - window.innerHeight * 0.22;
    requestAnimationFrame(() => window.scrollTo({ top: Math.max(0, top), behavior: reducedMotion() ? "auto" : "smooth" }));
  };

  // pins and their name tags, in px
  const placedPins: PlacedPin[] = pins
    .map((pin) => ({ pin, x: (pin.x - vx) * k, y: (pin.y - vy) * k }))
    .filter((p) => p.x > -12 && p.y > -12 && p.x < boxW + 12 && p.y < boxH + 12);
  const tags = boxW ? placeTags(placedPins, goal.z >= 2 ? 1 : small ? 5 : 3, boxW, boxH, small) : [];
  const tagged = new Set(tags.map((t) => t.pin.key));

  // printed names only where there's room: never on phones, never under a pin or a tag
  const blocked: Box[] = [...placedPins.map((p) => [p.x - 10, p.y - 10, 20, 20] as Box), ...tags.map((t) => [t.x - 2, t.y - 2, t.w + 4, t.h + 4] as Box)];
  const labels =
    k >= 0.45
      ? geo.labels.filter((l) => {
          const size = l.kind === "sea" ? 10.5 : 8.6;
          const w = l.text.length * (size * 0.62 + (l.kind === "sea" ? 2.6 : 1.1));
          const x = (l.at[0] - vx) * k;
          const y = (l.at[1] - vy) * k;
          return !blocked.some((b) => overlaps([x - w / 2, y - size, w, size + 2], b));
        })
      : [];

  // dragging moves the map once it's zoomed in
  const drag = useRef<{ x: number; y: number; cam: Camera; moved: boolean } | null>(null);
  const [dragging, setDragging] = useState(false);
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (goal.z === 1 || e.button !== 0 || (e.target as HTMLElement).closest("button")) return;
    drag.current = { x: e.clientX, y: e.clientY, cam: goal, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    if (!d.moved) setDragging(true);
    d.moved = true;
    go({ ...d.cam, cx: d.cam.cx - dx / kGoal, cy: d.cam.cy - dy / kGoal }, true);
  };
  const endDrag = () => {
    drag.current = null;
    setDragging(false);
  };
  const zoom = (factor: number) => {
    const at = factor > 1 && picked ? { cx: picked.x, cy: picked.y } : { cx: goal.cx, cy: goal.cy };
    go({ z: goal.z * factor, ...at });
  };

  let slip: ReactNode = null;
  if (pickedItems.length && pick === NOWHERE) {
    slip = (
      <PlaceSlip
        title="No place given"
        lead="In person or hybrid, but the platform doesn’t say where yet. Check the notice before you plan a trip."
        items={pickedItems}
        now={now}
        currency={currency}
        fx={fx}
        sheet={!wide}
        onClose={close}
      />
    );
  } else if (pickedItems.length && picked) {
    const soon = closingThisWeek(pickedItems, now);
    slip = (
      <PlaceSlip
        title={picked.label}
        lead={
          <>
            {picked.states.join(", ")}
            {picked.states.length > 0 && " · "}
            <b>{plural(pickedItems.length, "hackathon")}</b>
            {soon > 0 && ` · ${soon} close this week`}
            {picked.names.length > 1 && (
              <>
                <br />
                With {picked.names.slice(1).join(", ")}
              </>
            )}
          </>
        }
        others={pickedPin ? pickedPin.places.filter((p) => p !== picked) : []}
        onPickOther={(key) => choose(key, null, true)}
        items={pickedItems}
        showPlace={picked.names.length > 1}
        now={now}
        currency={currency}
        fx={fx}
        sheet={!wide}
        onClose={close}
        onShowAll={() => onShowCities(picked.names)}
      />
    );
  }

  return (
    <div className="mapview">
      <div className="mapview__main">
        <section className="mapsheet paper" aria-labelledby="mapsheet-title">
          <span className="pin mapsheet__pin mapsheet__pin--l" aria-hidden="true" />
          <span className="pin mapsheet__pin mapsheet__pin--r" aria-hidden="true" />
          <header className="mapsheet__head">
            <h2 id="mapsheet-title">
              India
              <small>
                {plural(placed.length, "hackathon")} in person &amp; hybrid · {plural(places.length, "place")}
              </small>
            </h2>
            <ul className="mapkey" aria-label="Pin colours">
              <li>
                <span className="pin" aria-hidden="true" />
                Open
              </li>
              <li>
                <span className="pin pin--red" aria-hidden="true" />
                Closes within 3 days
              </li>
              <li>
                <span className="pin pin--green" aria-hidden="true" />
                Happening now
              </li>
              <li>
                <span className="pin pin--blue" aria-hidden="true" />
                In your tabs
              </li>
            </ul>
          </header>

          <div
            ref={boxRef}
            className={`map${goal.z > 1 ? " is-zoomed" : ""}${dragging ? " is-dragging" : ""}`}
            style={{ aspectRatio: `${W} / ${H}` }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
          >
            {boxW > 0 && (
              <svg className="map__svg" viewBox={`${vx} ${vy} ${vw} ${vh}`} aria-hidden="true">
                <defs>
                  <path id="mv-coast" d={geo.outline + geo.neighbours} vectorEffect="non-scaling-stroke" />
                  <mask id="mv-sea" maskUnits="userSpaceOnUse" x={-300} y={-300} width={W + 600} height={H + 600}>
                    <rect x={-300} y={-300} width={W + 600} height={H + 600} fill="#fff" />
                    <use href="#mv-coast" fill="#000" stroke="#000" strokeWidth={2.5} />
                  </mask>
                </defs>
                <g mask="url(#mv-sea)" fill="none" strokeLinejoin="round">
                  {WATER.map(([w, c], i) => (
                    <use key={i} href="#mv-coast" stroke={c} strokeWidth={w} />
                  ))}
                </g>
                <path className="map__nb" d={geo.neighbours} />
                {geo.states.map((s) => (
                  <path key={s.name} className="map__state" d={s.d} />
                ))}
                <path className="map__inner" d={geo.inner} />
                <path className="map__outline" d={geo.outline} />
                <g className="map__labels">
                  {labels.map((l) => (
                    <text
                      key={l.text}
                      className={`map__label map__label--${l.kind}`}
                      x={l.at[0]}
                      y={l.at[1]}
                      fontSize={(l.kind === "sea" ? 10.5 : 8.6) / k}
                      letterSpacing={(l.kind === "sea" ? 2.6 : 1.1) / k}
                      textAnchor="middle"
                    >
                      {l.text}
                    </text>
                  ))}
                </g>
                {picked && <path className="map__loop" d={handLoop(picked.x, picked.y, 24 / k, 19 / k)} />}
              </svg>
            )}

            <div className="map__pins">
              {placedPins.map(({ pin, x, y }) => {
                const stack = pinStack(
                  pin.items.map((h) => pinFor(h, now, tracked[h.id])),
                  pin.items.length,
                );
                const on = pickedPin?.key === pin.key;
                return (
                  <button
                    key={pin.key}
                    data-key={pin.key}
                    type="button"
                    className={`mpin${on ? " is-on" : ""}`}
                    style={{ left: x, top: y }}
                    aria-label={`${pin.label}: ${plural(pin.items.length, "hackathon")}`}
                    aria-pressed={on}
                    onClick={(e) => choose(pin.places[0].key, e.currentTarget)}
                  >
                    {stack.map((colour, i) => (
                      <span
                        key={i}
                        className={`pin${colour === "brass" ? "" : ` pin--${colour}`}`}
                        style={{ translate: `${STACK_OFFSETS[stack.length][i][0]}px ${STACK_OFFSETS[stack.length][i][1]}px` }}
                      />
                    ))}
                    {pin.items.length > 1 && !tagged.has(pin.key) && <span className="mpin__n">{pin.items.length}</span>}
                  </button>
                );
              })}
              {tags.map((t) => (
                <span
                  key={t.pin.key}
                  className={`mtag${small ? " mtag--sm" : ""}${pickedPin?.key === t.pin.key ? " is-on" : ""}`}
                  style={{ left: t.x, top: t.y }}
                  aria-hidden="true"
                  onClick={() => choose(t.pin.places[0].key, null)}
                >
                  <b>{t.pin.items.length}</b> {t.pin.label}
                </span>
              ))}
            </div>

            {placed.length === 0 && (
              <p className="map__empty">
                Nothing in India matches these filters
                {abroad.length || online ? "; the ones that do are below the map." : "."}
              </p>
            )}

            <div className="map__ctl">
              <button type="button" onClick={() => zoom(2)} disabled={goal.z >= MAX_ZOOM} aria-label="Zoom in" title="Zoom in">
                <Plus size={16} aria-hidden="true" />
              </button>
              <button type="button" onClick={() => zoom(0.5)} disabled={goal.z <= 1} aria-label="Zoom out" title="Zoom out">
                <Minus size={16} aria-hidden="true" />
              </button>
              {goal.z > 1 && (
                <button type="button" onClick={() => go(WHOLE)} aria-label="Show all of India" title="Show all of India">
                  <Shrink size={15} aria-hidden="true" />
                </button>
              )}
            </div>
          </div>

          <p className="mapcredit">
            Pins mark the city, not the venue; more pins, busier city. Boundaries: Survey of India outline, via DataMeet (CC BY 4.0). Places:
            GeoNames (CC BY 4.0).
          </p>
        </section>

        {(online > 0 || abroad.length > 0 || nowhere.length > 0) && (
          <div className="offmap">
            {online > 0 && (
              <button type="button" className="slip" onClick={onShowOnline}>
                <span className="pin slip__pin" aria-hidden="true" />
                <Wifi size={14} aria-hidden="true" /> {plural(online, "online hackathon")}
                <span className="offmap__wide"> aren’t on the map</span>
                <ArrowRight size={14} aria-hidden="true" />
              </button>
            )}
            {abroad.length > 0 && (
              <button type="button" className="slip" onClick={() => onShowAbroad(abroadCountries)}>
                <span className="pin slip__pin" aria-hidden="true" />
                <Globe size={14} aria-hidden="true" /> {abroad.length} abroad
                <span className="offmap__wide">: see them in the list</span>
                <ArrowRight size={14} aria-hidden="true" />
              </button>
            )}
            {nowhere.length > 0 && (
              <button type="button" className={`slip${pick === NOWHERE ? " is-on" : ""}`} aria-pressed={pick === NOWHERE} onClick={(e) => choose(NOWHERE, e.currentTarget)}>
                <span className={`pin slip__pin${pick === NOWHERE ? " pin--blue" : ""}`} aria-hidden="true" />
                <MapPinOff size={14} aria-hidden="true" /> {nowhere.length} {nowhere.length === 1 ? "doesn’t" : "don’t"} say where yet
              </button>
            )}
          </div>
        )}

        {!wide && places.length > 0 && <PlaceIndex places={places} now={now} onPick={(p, el) => choose(p.key, el)} />}
      </div>

      {wide && (
        <div className="mapview__side">{slip || (places.length > 0 && <PlaceIndex places={places} now={now} onPick={(p, el) => choose(p.key, el)} aside />)}</div>
      )}
      {!wide && slip}
    </div>
  );
}

/** The places on the map as a ledger, busiest first: also the keyboard's way in. */
function PlaceIndex({ places, now, onPick, aside = false }: { places: Place[]; now: number; onPick: (p: Place, from: HTMLElement) => void; aside?: boolean }) {
  const [all, setAll] = useState(false);
  const shown = all ? places : places.slice(0, aside ? 12 : 10);
  return (
    <section className={`cityslip cityindex${aside ? "" : " cityindex--below"}`} aria-labelledby="cityindex-title">
      <span className="pin cityslip__pin" aria-hidden="true" />
      <h2 id="cityindex-title">Where they are</h2>
      <p className="cityslip__sub">The busiest places first. Pick one to see its notices.</p>
      <ol className="cityindex__list">
        {shown.map((p) => {
          const soon = closingThisWeek(p.items, now);
          return (
            <li key={p.key}>
              <button type="button" onClick={(e) => onPick(p, e.currentTarget)}>
                <span className="cityindex__n">{p.items.length}</span>
                <span className="cityindex__place">
                  {p.label}
                  <small>{p.names.length > 1 ? `with ${p.names.slice(1).join(", ")}` : p.states.join(", ")}</small>
                </span>
                {soon > 0 && <span className="cityindex__soon">{soon} close this week</span>}
              </button>
            </li>
          );
        })}
      </ol>
      {places.length > shown.length && (
        <button type="button" className="nb-more cityindex__all" onClick={() => setAll(true)}>
          Show all {places.length} places
        </button>
      )}
    </section>
  );
}

function PlaceSlip({
  title,
  lead,
  items,
  others = [],
  onPickOther,
  showPlace = false,
  now,
  currency,
  fx,
  sheet,
  onClose,
  onShowAll,
}: {
  title: string;
  lead: ReactNode;
  items: Hackathon[];
  others?: Place[];
  onPickOther?: (key: string) => void;
  showPlace?: boolean;
  now: number;
  currency: string;
  fx?: Record<string, number>;
  sheet: boolean;
  onClose: () => void;
  onShowAll?: () => void;
}) {
  const headRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => headRef.current?.focus({ preventScroll: true }), [title]);
  return (
    <section className={`cityslip${sheet ? " cityslip--sheet" : ""}`} aria-labelledby="cityslip-title">
      {!sheet && <span className="pin cityslip__pin" aria-hidden="true" />}
      <header className="cityslip__head">
        <h2 id="cityslip-title" ref={headRef} tabIndex={-1}>
          {title}
        </h2>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={18} aria-hidden="true" />
        </button>
      </header>
      <p className="cityslip__sub">{lead}</p>
      {others.length > 0 && (
        <p className="cityslip__also">
          On the same pin at this zoom:{" "}
          {others.map((o, i) => (
            <span key={o.key}>
              {i > 0 && ", "}
              <button type="button" onClick={() => onPickOther?.(o.key)}>
                {o.label} ({o.items.length})
              </button>
            </span>
          ))}
        </p>
      )}
      {onShowAll && (
        <button type="button" className="btn btn--sm btn--ink cityslip__all" onClick={onShowAll}>
          {items.length === 1 ? "Show it on the board" : `Show all ${items.length} on the board`}
        </button>
      )}
      <ol className="cityslip__list">
        {items.map((h) => {
          const prize = h.prize_amount ? prizeParts(h, currency, fx).main : undefined;
          return (
            <li key={h.id} className="crow">
              <div className="crow__date">
                <DeadlineStamp h={h} now={now} />
                <TimeLeft h={h} now={now} />
              </div>
              <div className="crow__body">
                <OpenNoticeLink id={h.id} className="crow__title">
                  {h.title}
                </OpenNoticeLink>
                <span className="crow__sub">
                  <b>{h.sourceName}</b>
                  {h.organizer && ` · ${h.organizer}`}
                  {showPlace && h.city && ` · ${h.city}`}
                  {prize && ` · ${prize}`}
                  {h.mode === "hybrid" && " · hybrid"}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
