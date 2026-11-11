export interface Env {
  /** Cloudflare D1: the hackathons, written by the home server's sync job. */
  DB: D1Database;
  /** The built web app (frontend/dist). */
  ASSETS: Fetcher;
  /** Shared with the sync job (HACKMASH_INGEST_KEY there). Set with `wrangler secret put INGEST_KEY`. */
  INGEST_KEY?: string;
}

/** A hackathon as stored in a row's `card` or `detail` JSON. */
export interface Item {
  id: string;
  source: string;
  title: string;
  url: string;
  mode?: string;
  kind?: string;
  organizer?: string;
  tagline?: string;
  location?: string;
  city?: string;
  country?: string;
  region?: string;
  starts_at?: string;
  ends_at?: string;
  registration_opens_at?: string;
  registration_deadline?: string;
  submission_deadline?: string;
  prize_text?: string;
  prize_usd?: number;
  participants?: number;
  first_seen_at?: string;
  tags?: string[];
  themes?: string[];
  audience?: string[];
  beginner_friendly?: boolean;
  registration_fee?: boolean;
  invite_only?: boolean;
  delisted?: boolean;
  also_on?: { id: string; source: string; url: string }[];
  [key: string]: unknown;
}

export interface SourceInfo {
  key: string;
  name: string;
  [key: string]: unknown;
}
