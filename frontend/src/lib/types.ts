export type Mode = "online" | "in_person" | "hybrid";
export type Kind = "hackathon" | "ideathon" | "coding_contest" | "data_science" | "other";
export type Status = "upcoming" | "open" | "live" | "ended";
export type DeadlineKind = "registration" | "submission" | "end" | "start";

export interface Listing {
  id: string;
  source: string;
  url: string;
}

/** One listing as published in /api/catalog. */
export interface RawItem {
  id: string;
  source: string;
  title: string;
  url: string;
  kind?: Kind;
  organizer?: string;
  tagline?: string;
  description?: string;
  image_url?: string;
  logo_url?: string;
  mode?: Mode;
  location?: string;
  city?: string;
  /** Indian state or union territory */
  state?: string;
  country?: string;
  region?: string;
  /** the city's coordinates: pins mark the city, not the venue */
  lat?: number;
  lng?: number;
  starts_at?: string;
  ends_at?: string;
  registration_opens_at?: string;
  registration_deadline?: string;
  submission_deadline?: string;
  timezone?: string;
  prize_text?: string;
  prize_amount?: number;
  prize_currency?: string;
  prize_usd?: number;
  non_cash_prizes?: boolean;
  tags?: string[];
  themes?: string[];
  audience?: string[];
  eligibility?: string[];
  participants?: number;
  team_size_min?: number;
  team_size_max?: number;
  registration_fee?: boolean;
  beginner_friendly?: boolean;
  travel_reimbursement?: boolean;
  invite_only?: boolean;
  duration_hours?: number;
  also_on?: Listing[];
  first_seen_at?: string;
  last_seen_at?: string;
  delisted?: boolean;
  hiring?: boolean;
  deadline_extended?: { field: "registration_deadline" | "submission_deadline"; old: string; new: string; seen_at: string };
}

/** A listing with client-side derived fields (parsed once on load). */
export interface Hackathon extends RawItem {
  sourceName: string;
  allSources: string[];
  start?: number;
  end?: number;
  regOpens?: number;
  regDeadline?: number;
  subDeadline?: number;
  firstSeen?: number;
  search: string;
}

export interface SourceInfo {
  key: string;
  name: string;
  homepage?: string;
  region: string;
  focus: string;
  description: string;
  enabled: boolean;
  count: number;
  last_run_at?: string | null;
  last_ok_at?: string | null;
  ok: boolean;
  error?: string | null;
}

export interface Taxonomy {
  themes: Record<string, string>;
  kinds: Record<string, string>;
  audiences: Record<string, string>;
  modes: Record<string, string>;
  regions: string[];
}

export interface Catalog {
  version: number;
  /** Changes with every sync; the feed's ETag. */
  data_version?: string;
  generated_at: string;
  count: number;
  taxonomy: Taxonomy;
  sources: SourceInfo[];
  fx?: Record<string, number>;
  items: RawItem[];
}
