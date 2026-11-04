/**
 * The personal tracker. Everything lives in this browser's localStorage; nothing
 * is sent anywhere. Each entry keeps a snapshot of the listing so it survives
 * after the hackathon ends and drops out of the catalog.
 */
import { useSyncExternalStore } from "react";
import { guessCurrency } from "./format";
import type { Hackathon } from "./types";

const KEY = "hackmash:v1";

export type TrackStatus = "saved" | "applied" | "submitted" | "shortlisted" | "won" | "lost" | "withdrawn";

export const TRACK_STATUSES: { key: TrackStatus; label: string; hint: string }[] = [
  { key: "saved", label: "Saved", hint: "Considering it" },
  { key: "applied", label: "Applied", hint: "Registered on the platform" },
  { key: "submitted", label: "Submitted", hint: "Project handed in" },
  { key: "shortlisted", label: "Shortlisted", hint: "Through to a later round or the finale" },
  { key: "won", label: "Won", hint: "Placed or took a prize" },
  { key: "lost", label: "Didn't place", hint: "Finished without a prize" },
  { key: "withdrawn", label: "Dropped", hint: "Not doing it after all" },
];

export const STATUS_LABEL = Object.fromEntries(TRACK_STATUSES.map((s) => [s.key, s.label])) as Record<TrackStatus, string>;

export const CHECKLIST: { key: string; label: string }[] = [
  { key: "registered", label: "Registered on the platform" },
  { key: "team", label: "Team confirmed" },
  { key: "rules", label: "Read the rules and judging criteria" },
  { key: "idea", label: "Idea picked" },
  { key: "repo", label: "Repo started (fresh commits only)" },
  { key: "demo", label: "Demo video recorded" },
  { key: "deck", label: "Pitch deck / README ready" },
  { key: "submitted", label: "Submitted before the deadline" },
];

export interface Snapshot {
  title: string;
  url: string;
  source: string;
  sourceName: string;
  organizer?: string;
  logo_url?: string;
  mode?: string;
  location?: string;
  prize_text?: string;
  starts_at?: string;
  ends_at?: string;
  registration_deadline?: string;
  submission_deadline?: string;
}

export interface Tracked {
  id: string;
  status: TrackStatus;
  addedAt: number;
  updatedAt: number;
  notes?: string;
  team?: string;
  projectUrl?: string;
  prizeWon?: string;
  checklist?: Record<string, boolean>;
  snapshot: Snapshot;
}

export interface PinnedSearch {
  id: string;
  name: string;
  query: string;
  createdAt: number;
}

export interface BusyRange {
  id: string;
  label: string;
  from: string; // yyyy-mm-dd
  to: string;
}

export interface StoreData {
  version: 1;
  items: Record<string, Tracked>;
  dismissed: string[];
  pinned: PinnedSearch[];
  busy: BusyRange[];
  lastVisit?: number;
  currency?: string;
}

const EMPTY: StoreData = { version: 1, items: {}, dismissed: [], pinned: [], busy: [] };

function read(): StoreData {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...EMPTY };
    const data = JSON.parse(raw) as Partial<StoreData>;
    return {
      version: 1,
      items: data.items && typeof data.items === "object" ? data.items : {},
      dismissed: Array.isArray(data.dismissed) ? data.dismissed : [],
      pinned: Array.isArray(data.pinned) ? data.pinned : [],
      busy: Array.isArray(data.busy) ? data.busy : [],
      lastVisit: typeof data.lastVisit === "number" ? data.lastVisit : undefined,
      currency: typeof data.currency === "string" ? data.currency : undefined,
    };
  } catch {
    return { ...EMPTY };
  }
}

let state: StoreData = typeof localStorage === "undefined" ? { ...EMPTY } : read();
const listeners = new Set<() => void>();

/** When the visitor was last here, captured once per page load ("new since your last visit"). */
export const previousVisit: number | undefined = state.lastVisit;

function commit(next: StoreData) {
  state = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage full or blocked: keep working in memory */
  }
  for (const l of listeners) l();
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key === KEY) {
      state = read();
      for (const l of listeners) l();
    }
  });
  // stamp this visit a little later so a quick reload still shows the same "new" set
  window.setTimeout(() => commit({ ...state, lastVisit: Date.now() }), 15_000);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useStore(): StoreData {
  return useSyncExternalStore(subscribe, () => state, () => state);
}

export function getStore(): StoreData {
  return state;
}

function snapshotOf(h: Hackathon): Snapshot {
  return {
    title: h.title,
    url: h.url,
    source: h.source,
    sourceName: h.sourceName,
    organizer: h.organizer,
    logo_url: h.logo_url,
    mode: h.mode,
    location: h.location,
    prize_text: h.prize_text,
    starts_at: h.starts_at,
    ends_at: h.ends_at,
    registration_deadline: h.registration_deadline,
    submission_deadline: h.submission_deadline,
  };
}

export const tracker = {
  track(h: Hackathon, status: TrackStatus) {
    const now = Date.now();
    const prev = state.items[h.id];
    const checklist = { ...(prev?.checklist ?? {}) };
    if (status !== "saved" && status !== "withdrawn") checklist.registered = true;
    if (status === "submitted" || status === "shortlisted" || status === "won" || status === "lost") checklist.submitted = true;
    commit({
      ...state,
      items: {
        ...state.items,
        [h.id]: { ...prev, id: h.id, status, addedAt: prev?.addedAt ?? now, updatedAt: now, checklist, snapshot: snapshotOf(h) },
      },
      dismissed: state.dismissed.filter((d) => d !== h.id),
    });
  },
  setStatus(id: string, status: TrackStatus) {
    const prev = state.items[id];
    if (!prev) return;
    const checklist = { ...(prev.checklist ?? {}) };
    if (status !== "saved" && status !== "withdrawn") checklist.registered = true;
    if (status === "submitted" || status === "shortlisted" || status === "won" || status === "lost") checklist.submitted = true;
    commit({ ...state, items: { ...state.items, [id]: { ...prev, status, checklist, updatedAt: Date.now() } } });
  },
  patch(id: string, patch: Partial<Omit<Tracked, "id" | "snapshot">>) {
    const prev = state.items[id];
    if (!prev) return;
    commit({ ...state, items: { ...state.items, [id]: { ...prev, ...patch, updatedAt: Date.now() } } });
  },
  refreshSnapshot(h: Hackathon) {
    const prev = state.items[h.id];
    if (!prev) return;
    const snap = snapshotOf(h);
    if (JSON.stringify(snap) === JSON.stringify(prev.snapshot)) return;
    commit({ ...state, items: { ...state.items, [h.id]: { ...prev, snapshot: snap } } });
  },
  /** Put back an entry exactly as it was (undo for remove). */
  restore(entry: Tracked) {
    commit({ ...state, items: { ...state.items, [entry.id]: entry } });
  },
  untrack(id: string) {
    const items = { ...state.items };
    delete items[id];
    commit({ ...state, items });
  },
  dismiss(id: string) {
    if (state.dismissed.includes(id)) return;
    commit({ ...state, dismissed: [...state.dismissed, id] });
  },
  undismiss(id: string) {
    commit({ ...state, dismissed: state.dismissed.filter((d) => d !== id) });
  },
  pinSearch(name: string, query: string) {
    const entry: PinnedSearch = { id: Math.random().toString(36).slice(2, 9), name, query, createdAt: Date.now() };
    commit({ ...state, pinned: [...state.pinned.filter((p) => p.query !== query), entry].slice(-12) });
  },
  unpinSearch(id: string) {
    commit({ ...state, pinned: state.pinned.filter((p) => p.id !== id) });
  },
  addBusy(label: string, from: string, to: string) {
    const entry: BusyRange = { id: Math.random().toString(36).slice(2, 9), label: label || "Busy", from, to: to || from };
    commit({ ...state, busy: [...state.busy, entry].sort((a, b) => a.from.localeCompare(b.from)) });
  },
  removeBusy(id: string) {
    commit({ ...state, busy: state.busy.filter((b) => b.id !== id) });
  },
  setCurrency(currency: string) {
    commit({ ...state, currency });
  },
  exportJSON(): string {
    return JSON.stringify({ app: "hackmash", exportedAt: new Date().toISOString(), ...state }, null, 2);
  },
  /** Merge an exported file into this browser. Newer entries win. Returns how many entries were added or updated. */
  importJSON(text: string): number {
    const data = JSON.parse(text) as Partial<StoreData> & { app?: string };
    if (!data || typeof data !== "object" || !data.items || typeof data.items !== "object") {
      throw new Error("That file is not a Hackmash export.");
    }
    const items = { ...state.items };
    let changed = 0;
    for (const [id, entry] of Object.entries(data.items)) {
      if (!entry || typeof entry !== "object" || !entry.snapshot?.title || !entry.status) continue;
      const mine = items[id];
      if (!mine || (entry.updatedAt ?? 0) > mine.updatedAt) {
        items[id] = { ...entry, id };
        changed++;
      }
    }
    const dismissed = [...new Set([...state.dismissed, ...(data.dismissed ?? [])])];
    const pinned = [...state.pinned];
    for (const p of data.pinned ?? []) if (!pinned.some((x) => x.query === p.query)) pinned.push(p);
    const busy = [...state.busy];
    for (const b of data.busy ?? []) if (!busy.some((x) => x.from === b.from && x.to === b.to)) busy.push(b);
    commit({ ...state, items, dismissed, pinned, busy });
    return changed;
  },
};

export function currencyPref(s: StoreData): string {
  return s.currency ?? guessCurrency();
}

/** Busy ranges as [start of first day, end of last day] in local time. */
export function busyRanges(s: StoreData): { from: number; to: number; label: string }[] {
  return s.busy.map((b) => ({ label: b.label, from: Date.parse(`${b.from}T00:00:00`), to: Date.parse(`${b.to}T23:59:59`) }));
}
