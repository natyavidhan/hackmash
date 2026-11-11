import type { Hackathon } from "./types";

/** Push pins carry state on the map as on the board; the map shows the most pressing first. */
export type PinColour = "red" | "blue" | "green" | "brass";
const PRIORITY: PinColour[] = ["red", "blue", "green", "brass"];

export interface CityGroup {
  key: string;
  city: string;
  state?: string;
  x: number;
  y: number;
  items: Hackathon[];
}

/**
 * A place students would name: a city with the towns right around it ("Delhi NCR"
 * is Delhi, Noida, Gurugram...). Fixed at one radius, so the list of places and
 * what a pick shows don't change with screen size or zoom.
 */
export interface Place {
  key: string; // the biggest city's key
  name: string; // the biggest city
  label: string; // "Delhi NCR", "Pune"
  x: number; // map units, at the biggest city
  y: number;
  items: Hackathon[];
  cities: string[]; // city keys, biggest first
  names: string[];
  states: string[];
}

/** One pin on the map: a place, plus any others too close to tell apart at this zoom. */
export interface Pin {
  key: string;
  label: string; // the biggest place, "+1" for each other place on the pin
  x: number;
  y: number;
  places: Place[]; // biggest first
  items: Hackathon[];
}

export const cityKey = (h: { city?: string; state?: string }) => `${h.city ?? ""}|${h.state ?? ""}`;

export function groupByCity(items: Hackathon[], project: (lon: number, lat: number) => [number, number]): CityGroup[] {
  const groups = new Map<string, CityGroup>();
  for (const h of items) {
    if (h.lat === undefined || h.lng === undefined) continue;
    const key = cityKey(h);
    let g = groups.get(key);
    if (!g) {
      const [x, y] = project(h.lng, h.lat);
      g = { key, city: h.city ?? "", state: h.state, x, y, items: [] };
      groups.set(key, g);
    }
    g.items.push(h);
  }
  return [...groups.values()];
}

// a place that gathers a metro's satellite towns is named for the metro
const METRO: Record<string, string> = { Delhi: "Delhi NCR", Mumbai: "Mumbai region" };

/** Biggest city first; a smaller one within `reach` (map units) belongs to its place. */
export function groupPlaces(groups: CityGroup[], reach: number): Place[] {
  const out: Place[] = [];
  const sorted = [...groups].sort((a, b) => b.items.length - a.items.length || a.city.localeCompare(b.city));
  for (const g of sorted) {
    const near = out.find((p) => Math.hypot(p.x - g.x, p.y - g.y) <= reach);
    if (near) {
      near.items.push(...g.items);
      near.cities.push(g.key);
      near.names.push(g.city);
      if (g.state && !near.states.includes(g.state)) near.states.push(g.state);
    } else {
      out.push({ key: g.key, name: g.city, label: g.city, x: g.x, y: g.y, items: [...g.items], cities: [g.key], names: [g.city], states: g.state ? [g.state] : [] });
    }
  }
  for (const p of out) if (p.names.length > 1 && METRO[p.name]) p.label = METRO[p.name];
  return out.sort((a, b) => b.items.length - a.items.length || a.label.localeCompare(b.label));
}

/** Places closer than `radius` (map units, i.e. a few pixels at this zoom) share a pin. */
export function clusterPins(places: Place[], radius: number): Pin[] {
  const out: Pin[] = [];
  for (const p of places) {
    const near = out.find((pin) => Math.hypot(pin.x - p.x, pin.y - p.y) < radius);
    if (near) {
      near.places.push(p);
      near.items.push(...p.items);
    } else out.push({ key: p.key, label: p.label, x: p.x, y: p.y, places: [p], items: [...p.items] });
  }
  for (const pin of out) if (pin.places.length > 1) pin.label = `${pin.places[0].label} +${pin.places.length - 1}`;
  return out;
}

/** One pin for a quiet city, two from 3 events, three from 10: a busy city looks busy. */
export function pinStack(colours: PinColour[], count: number): PinColour[] {
  const present = PRIORITY.filter((c) => colours.includes(c));
  const size = count >= 10 ? 3 : count >= 3 ? 2 : 1;
  return Array.from({ length: size }, (_, i) => present[i] ?? "brass");
}

export const STACK_OFFSETS: Record<number, [number, number][]> = {
  1: [[0, 0]],
  2: [[-4, -2], [4, 2]],
  3: [[-5, -3], [5, -3], [0, 4]],
};

export interface PlacedPin {
  pin: Pin;
  x: number; // px inside the map box
  y: number;
}

export interface Tag {
  pin: Pin;
  x: number;
  y: number;
  w: number;
  h: number;
}

export type Box = [number, number, number, number];
export const overlaps = (a: Box, b: Box) => a[0] < b[0] + b[2] && a[0] + a[2] > b[0] && a[1] < b[1] + b[3] && a[1] + a[3] > b[1];

/**
 * Name tags for the busiest pins, placed where they cover no other pin or tag
 * (right, left, then above and below). A pin too crowded to name keeps its count.
 */
export function placeTags(pins: PlacedPin[], minCount: number, boxW: number, boxH: number, small: boolean): Tag[] {
  const placed: Box[] = [];
  const pinBoxes: Box[] = pins.map((p) => [p.x - 9, p.y - 9, 18, 18]);
  const free = (b: Box) => b[0] >= 2 && b[1] >= 2 && b[0] + b[2] <= boxW - 2 && b[1] + b[3] <= boxH - 2 && !placed.some((p) => overlaps(b, p));
  const tags: Tag[] = [];
  for (const p of [...pins].sort((a, b) => b.pin.items.length - a.pin.items.length)) {
    const n = p.pin.items.length;
    if (n < minCount) continue;
    const w = (small ? 14 : 18) + (String(n).length + p.pin.label.length) * (small ? 5.5 : 6.2);
    const h = small ? 16 : 18;
    const { x, y } = p;
    const spots: [number, number][] = [
      [x + 11, y - h / 2], [x - 11 - w, y - h / 2], [x + 6, y - h - 7], [x + 6, y + 8], [x - w - 6, y - h - 7], [x - w - 6, y + 8],
      [x - w / 2, y + 11], [x - w / 2, y - h - 11], [x + 16, y - h - 12], [x + 16, y + 12], [x - w - 16, y + 12], [x - w - 16, y - h - 12],
    ];
    const boxes = spots.map(([bx, by]) => [bx, by, w, h] as Box);
    // a busy city always gets its name, even over a quiet neighbour's pin
    const box = boxes.find((b) => free(b) && !pinBoxes.some((pb) => overlaps(b, pb))) ?? (n >= 10 ? boxes.find(free) : undefined);
    if (!box) continue;
    placed.push(box);
    tags.push({ pin: p.pin, x: box[0], y: box[1], w, h });
  }
  return tags;
}

/** A loop drawn in ballpoint around a point: wobbles a little and overshoots where it began. */
export function handLoop(cx: number, cy: number, rx: number, ry: number, seed = 1.3): string {
  const n = 30;
  const start = -2.4 + seed * 0.4;
  const sweep = Math.PI * 2 + 0.55;
  const pts: [number, number][] = [];
  for (let i = 0; i <= n; i++) {
    const t = start + (sweep * i) / n;
    const w = 1 + 0.05 * Math.sin(3 * t + seed) + 0.03 * Math.cos(5 * t + 2 * seed) + (i / n) * 0.07;
    pts.push([cx + rx * w * Math.cos(t), cy + ry * w * Math.sin(t)]);
  }
  let d = `M${pts[0][0].toFixed(2)},${pts[0][1].toFixed(2)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const [p1, p2] = [pts[i], pts[i + 1]];
    const p3 = pts[i + 2] ?? p2;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += `C${c1[0].toFixed(2)},${c1[1].toFixed(2)} ${c2[0].toFixed(2)},${c2[1].toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`;
  }
  return d;
}
