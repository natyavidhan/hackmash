// Bakes the map of India the Map view and the state picker draw.
//
//   cd frontend && node scripts/build-india-map.mjs
//
// Writes src/assets/india-map.json (the Map view) and src/assets/india-states.json
// (the small state picker in the filters). Needs network and npx (for mapshaper).
//
// Sources, pinned to a commit:
// - States and union territories: DataMeet India community, CC BY 4.0
//   (https://github.com/datameet/maps). India's outline as the Survey of India
//   draws it: all of Jammu and Kashmir and Ladakh, and Arunachal Pradesh.
// - Neighbouring countries: Natural Earth (public domain), its India-worldview
//   edition, so borders match the official map.
//
// Outlines are projected here with the projection the browser uses for pins
// (src/lib/projection.ts), so the two always agree.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { conicConformal } from "../src/lib/projection.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ASSETS = path.join(HERE, "..", "src", "assets");
const MAPSHAPER = "mapshaper@0.6.121";
const STATES_URL = "https://raw.githubusercontent.com/datameet/maps/b3fbbde595310b397a55d718e0958ce249a4fa1f/States/Admin2";
const WORLD_URL =
  "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/ca96624a56bd078437bca8184e78163e5039ad19/10m_cultural/ne_10m_admin_0_countries_ind";
const ATTRIBUTION = "State boundaries: DataMeet India community (CC BY 4.0). Neighbours: Natural Earth.";

const W = 1000; // map units across
const PAD = [40, 30];
const SPEC = { lon0: 80, phi0: 12, phi1: 28 };

// DataMeet's names -> the site's (backend/hackmash/geo.py STATES)
const RENAME = { "Andaman & Nicobar": "Andaman and Nicobar", "Jammu & Kashmir": "Jammu and Kashmir" };
const STATES = [
  "Andaman and Nicobar", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh", "Chhattisgarh",
  "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
  "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra",
  "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim",
  "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
];
// state names printed on the big map: where the shape's centre is a poor spot, a nudge (map units)
const STATE_LABELS = {
  Rajasthan: [-26, 4], "Madhya Pradesh": [-50, 30], Maharashtra: [-36, -18], "Uttar Pradesh": [-20, 18], Gujarat: [-6, 16],
  Karnataka: [-12, 12], "Andhra Pradesh": [16, 34], Telangana: [0, -12], Odisha: [8, 12], Chhattisgarh: [0, 22],
  "Tamil Nadu": [-8, 0], Bihar: [6, 0], Jharkhand: [0, 6], "West Bengal": [10, 30], Ladakh: [20, 30],
  "Jammu and Kashmir": [-14, 16], "Arunachal Pradesh": [6, -4], Assam: [-10, 8], Kerala: [-6, 26], Punjab: [-8, 0],
  Haryana: [-8, 10], "Himachal Pradesh": [6, 0], Uttarakhand: [10, 4],
};
const SHORT = { "Jammu and Kashmir": "J & K", "Himachal Pradesh": "Himachal", "Arunachal Pradesh": "Arunachal" };
const PLACE_LABELS = [
  ["sea", "Arabian Sea", 70.9, 13.0], ["sea", "Bay of Bengal", 87.6, 15.2], ["sea", "Indian Ocean", 75.6, 7.3],
  ["country", "Pakistan", 68.2, 27.6], ["country", "China", 86.6, 32.6], ["country", "Nepal", 84.0, 28.35],
  ["country", "Bangladesh", 90.4, 23.6], ["country", "Myanmar", 95.6, 21.6], ["country", "Sri Lanka", 80.8, 7.6],
];

async function download(base, exts, dir, name) {
  for (const ext of exts) {
    const res = await fetch(`${base}.${ext}`);
    if (!res.ok) throw new Error(`${base}.${ext}: HTTP ${res.status}`);
    fs.writeFileSync(path.join(dir, `${name}.${ext}`), Buffer.from(await res.arrayBuffer()));
  }
}

function mapshaper(dir, args) {
  execFileSync("npx", ["--yes", MAPSHAPER, ...args], { cwd: dir, stdio: ["ignore", "ignore", "inherit"] });
}

const readGeo = (file) => {
  const doc = JSON.parse(fs.readFileSync(file, "utf8"));
  if (doc.type === "FeatureCollection") return doc.features;
  if (doc.type === "GeometryCollection") return doc.geometries.map((geometry) => ({ properties: {}, geometry }));
  return [{ properties: {}, geometry: doc }];
};
const rings = (g) => (g.type === "Polygon" ? g.coordinates : g.type === "MultiPolygon" ? g.coordinates.flat() : []);
const lines = (g) => (g.type === "LineString" ? [g.coordinates] : g.type === "MultiLineString" ? g.coordinates : []);

function main(dir) {
  // -- shapes, simplified in kilometres so detail is even across the country
  mapshaper(dir, ["states.shp", "-rename-fields", "name=ST_NM", "-simplify", "interval=2500", "keep-shapes", "-clean",
    "-o", "full.json", "format=geojson", "precision=0.0001"]);
  mapshaper(dir, ["full.json", "-innerlines", "-o", "inner.json", "format=geojson", "precision=0.0001"]);
  mapshaper(dir, ["full.json", "-dissolve", "-o", "outline.json", "format=geojson", "precision=0.0001"]);
  mapshaper(dir, ["states.shp", "-rename-fields", "name=ST_NM", "-simplify", "interval=12000", "keep-shapes", "-clean",
    "-o", "mini.json", "format=geojson", "precision=0.001"]);
  mapshaper(dir, ["mini.json", "-dissolve", "-o", "mini-outline.json", "format=geojson", "precision=0.001"]);
  mapshaper(dir, ["world.shp", "-filter", "ADM0_A3 !== 'IND'", "-clip", "bbox=56,-4,108,46", "-simplify", "interval=6000",
    "keep-shapes", "-clean", "-o", "neighbours.json", "format=geojson", "precision=0.001"]);

  // -- fit India's outline to W map units across
  const raw = conicConformal(SPEC.lon0, SPEC.phi0, SPEC.phi1);
  const outline = readGeo(path.join(dir, "outline.json"));
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const f of outline) for (const ring of rings(f.geometry)) for (const [lon, lat] of ring) {
    const [x, y] = raw(lon, lat);
    x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  const k = (W - 2 * PAD[0]) / (x1 - x0);
  const projection = { ...SPEC, k: +k.toFixed(4), tx: +(PAD[0] - k * x0).toFixed(3), ty: +(PAD[1] + k * y1).toFixed(3) };
  const H = Math.ceil(k * (y1 - y0) + 2 * PAD[1]);
  const project = (lon, lat) => {
    const [x, y] = raw(lon, lat);
    return [projection.tx + projection.k * x, projection.ty - projection.k * y];
  };

  // -- SVG path data, relative moves, rounded
  const num = (v) => {
    const s = (+v.toFixed(3)).toString();
    return s.replace(/^(-?)0\./, "$1.");
  };
  const pathOf = (coords, digits, close) => {
    const f = 10 ** digits;
    const pts = [];
    for (const [lon, lat] of coords) {
      const [x, y] = project(lon, lat);
      const p = [Math.round(x * f), Math.round(y * f)];
      const q = pts[pts.length - 1];
      if (!q || q[0] !== p[0] || q[1] !== p[1]) pts.push(p);
    }
    if (close && pts.length > 1 && pts[0][0] === pts[pts.length - 1][0] && pts[0][1] === pts[pts.length - 1][1]) pts.pop();
    if (pts.length < (close ? 3 : 2)) return "";
    let d = `M${num(pts[0][0] / f)} ${num(pts[0][1] / f)}l`;
    let prev = pts[0];
    pts.slice(1).forEach((p, i) => {
      const dx = num((p[0] - prev[0]) / f);
      const dy = num((p[1] - prev[1]) / f);
      d += `${i === 0 || dx.startsWith("-") ? "" : " "}${dx}${dy.startsWith("-") ? "" : " "}${dy}`;
      prev = p;
    });
    return d + (close ? "z" : "");
  };
  const polyPath = (g, digits) => rings(g).map((r) => pathOf(r, digits, true)).join("");
  const linePath = (g, digits) => lines(g).map((l) => pathOf(l, digits, false)).join("");
  const anchor = (g) => {
    // centroid of the largest ring, in map units
    let best = null;
    for (const ring of rings(g)) {
      const pts = ring.map(([lon, lat]) => project(lon, lat));
      let a = 0, cx = 0, cy = 0;
      for (let i = 0; i < pts.length - 1; i++) {
        const c = pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1];
        a += c; cx += (pts[i][0] + pts[i + 1][0]) * c; cy += (pts[i][1] + pts[i + 1][1]) * c;
      }
      if (a && (!best || Math.abs(a) > Math.abs(best.a))) best = { a, x: cx / (3 * a), y: cy / (3 * a) };
    }
    return best;
  };
  const statesOf = (file, digits) => {
    const list = readGeo(path.join(dir, file)).map((f) => {
      const name = RENAME[f.properties.name] ?? f.properties.name;
      const a = anchor(f.geometry);
      return { name, d: polyPath(f.geometry, digits), at: [+a.x.toFixed(1), +a.y.toFixed(1)], area: Math.round(Math.abs(a.a) / 2) };
    });
    const names = new Set(list.map((s) => s.name));
    const missing = STATES.filter((s) => !names.has(s));
    const unknown = [...names].filter((s) => !STATES.includes(s));
    if (missing.length || unknown.length) throw new Error(`state names: missing ${missing}, unknown ${unknown}`);
    return list.sort((a, b) => a.name.localeCompare(b.name));
  };

  const states = statesOf("full.json", 1);
  const labels = [
    ...states
      .filter((s) => STATE_LABELS[s.name])
      .map((s) => ({ kind: "state", text: (SHORT[s.name] ?? s.name).toUpperCase(), at: [+(s.at[0] + STATE_LABELS[s.name][0]).toFixed(1), +(s.at[1] + STATE_LABELS[s.name][1]).toFixed(1)] })),
    ...PLACE_LABELS.map(([kind, text, lon, lat]) => ({ kind, text: text.toUpperCase(), at: project(lon, lat).map((v) => +v.toFixed(1)) })),
  ];
  const full = {
    attribution: ATTRIBUTION,
    width: W,
    height: H,
    projection,
    states: states.map(({ name, d, at }) => ({ name, d, at })),
    inner: readGeo(path.join(dir, "inner.json")).map((f) => linePath(f.geometry, 1)).join(""),
    outline: outline.map((f) => polyPath(f.geometry, 1)).join(""),
    neighbours: readGeo(path.join(dir, "neighbours.json")).map((f) => polyPath(f.geometry, 1)).join(""),
    labels,
  };
  const mini = {
    attribution: ATTRIBUTION,
    width: W,
    height: H,
    states: statesOf("mini.json", 0),
    outline: readGeo(path.join(dir, "mini-outline.json")).map((f) => polyPath(f.geometry, 0)).join(""),
  };
  for (const [file, doc] of [["india-map.json", full], ["india-states.json", mini]]) {
    const text = JSON.stringify(doc);
    fs.writeFileSync(path.join(ASSETS, file), text + "\n");
    console.log(`${file}: ${(text.length / 1024).toFixed(0)} KB`);
  }
  console.log(`map: ${W} x ${H} units, projection`, projection);
}

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "india-map-"));
try {
  await download(STATES_URL, ["shp", "shx", "dbf", "prj"], dir, "states");
  await download(WORLD_URL, ["shp", "shx", "dbf", "prj"], dir, "world");
  main(dir);
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}
