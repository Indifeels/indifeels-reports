// Nimbata payload normaliser — shared by nimbata-webhook and nimbata-sync.
// Nimbata lets each account choose and RENAME webhook fields, and the API may use different keys,
// so every field is matched against a list of aliases after flattening and normalising keys
// (lower-case, letters/digits only). Missing optional fields simply stay null.

export type CallRow = Record<string, unknown> & { nimbata_call_id: string; is_test: boolean };

const MEL = "Australia/Melbourne";

function norm(k: string): string {
  return k.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function flatten(obj: unknown, prefix = "", out: Record<string, unknown> = {}): Record<string, unknown> {
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      const key = prefix ? prefix + "." + k : k;
      if (v && typeof v === "object" && !Array.isArray(v)) flatten(v, key, out);
      else {
        out[norm(key)] = v;
        if (!(norm(k) in out)) out[norm(k)] = v; // leaf name also reachable without its parent prefix
      }
    }
  }
  return out;
}

function pick(f: Record<string, unknown>, aliases: string[]): unknown {
  for (const a of aliases) {
    const v = f[norm(a)];
    if (v === undefined || v === null) continue;
    if (typeof v === "string" && v.trim() === "") continue;
    return v;
  }
  return null;
}

function str(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" ? (x as any)?.name ?? JSON.stringify(x) : String(x))).join(", ") || null;
  const s = String(v).trim();
  return s === "" ? null : s.slice(0, 2000);
}

function int(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "string" && /^\d{1,2}:\d{2}(:\d{2})?$/.test(v.trim())) { // "mm:ss" or "hh:mm:ss"
    const p = v.trim().split(":").map(Number);
    return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
  }
  const n = Number(String(v).replace(/[^0-9.\-]/g, ""));
  return Number.isFinite(n) ? Math.round(n) : null;
}

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(String(v).replace(/[^0-9.\-]/g, ""));
  return Number.isFinite(n) ? Math.round(n * 100) / 100 : null;
}

function bool(v: unknown): boolean | null {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "boolean") return v;
  const s = String(v).trim().toLowerCase();
  if (["y", "yes", "true", "1", "qualified"].includes(s)) return true;
  if (["n", "no", "false", "0", "unqualified", "not qualified"].includes(s)) return false;
  return null;
}

function url(v: unknown): string | null {
  const s = str(v);
  return s && /^https?:\/\//i.test(s) ? s : null;
}

// Melbourne wall-clock "YYYY-MM-DD HH:mm:ss" -> UTC ISO (DST-safe)
export function melbourneToUtc(y: number, mo: number, d: number, h = 0, mi = 0, s = 0): string {
  const guess = Date.UTC(y, mo - 1, d, h, mi, s);
  const offset = (t: number) => {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
      timeZone: MEL, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).formatToParts(new Date(t)).map((x) => [x.type, x.value]));
    return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - t;
  };
  let t = guess - offset(guess);
  t = guess - offset(t);
  return new Date(t).toISOString();
}

function ts(v: unknown, localMelbourne: boolean): string | null {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number" || /^\d{10,13}$/.test(String(v))) {
    const n = Number(v);
    return new Date(n < 1e12 ? n * 1000 : n).toISOString();
  }
  const s = String(v).trim();
  if (/[zZ]$|[+\-]\d{2}:?\d{2}$/.test(s)) {
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d.toISOString();
  }
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (m) {
    const parts = [+m[1], +m[2], +m[3], +m[4], +m[5], +(m[6] || 0)] as const;
    return localMelbourne
      ? melbourneToUtc(...parts)
      : new Date(Date.UTC(parts[0], parts[1] - 1, parts[2], parts[3], parts[4], parts[5])).toISOString();
  }
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d.toISOString();
}

export function toE164AU(v: string | null): string | null {
  if (!v) return null;
  const plus = v.trim().startsWith("+");
  const d = v.replace(/\D/g, "");
  if (!d) return null;
  if (plus) return "+" + d;
  if (d.startsWith("61") && d.length >= 11) return "+" + d;
  if (d.startsWith("0") && d.length === 10) return "+61" + d.slice(1);
  if (d.length === 9 && /^[2-478]/.test(d)) return "+61" + d;
  return d.length >= 8 ? "+" + d : null;
}

const TEST_RE = /\b(test|sample|example|dummy|lorem)\b/i;

export function normalise(payload: Record<string, unknown>): { row: CallRow | null; fields: string[]; error?: string } {
  const f = flatten(payload);
  const fields = Object.keys(payload).slice(0, 80);
  const id = str(pick(f, ["Unique Call ID", "unique_call_id", "call_id", "callId", "callUuid", "uuid", "uid", "id", "nimbata_call_id"]));
  if (!id) return { row: null, fields, error: "no call identifier in payload" };

  const statusRaw = str(pick(f, ["Call Outcome", "call_outcome_status", "call_status", "callStatus", "status", "disposition_status"]));
  const st = (statusRaw || "").toUpperCase().replace(/\s+/g, "_");
  const talk = int(pick(f, ["Talk Duration", "talk_duration", "talkDuration", "talk_time", "billsec"]));
  let answered: boolean | null = null;
  if (/^ANSWERED$|COMPLETED|CONNECTED/.test(st)) answered = true;
  else if (/NOT_ANSWERED|NO_ANSWER|MISSED|BLOCKED|BUSY|FAILED|VOICEMAIL|ABANDON/.test(st)) answered = false;
  else if (talk !== null) answered = talk > 0;
  if (st === "IN_PROGRESS") answered = null;

  const freq = int(pick(f, ["Call Frequency", "call_frequency", "callFrequency", "caller_call_count"]));
  const firstFlag = bool(pick(f, ["first_time_caller", "firstTimeCaller", "new_caller", "is_first_call"]));
  const first = firstFlag ?? (freq !== null ? freq <= 1 : null);

  const caller = str(pick(f, ["Caller ID (international)", "caller_id_international", "Caller ID", "caller_id", "callerId", "caller_number", "caller", "from", "from_number"]));
  const tags = str(pick(f, ["Tags", "tags", "tag", "call_tag", "labels"]));
  const qualifiedField = bool(pick(f, ["qualified", "qualified_lead", "qualifiedLead", "is_qualified", "lead_qualified"]));
  // Only an explicit qualified flag or an explicit "qualified" tag counts — nothing is inferred from duration.
  const qualified = qualifiedField ?? (tags ? (/\bqualified\b/i.test(tags) && !/\b(un|not[\s_-]?)qualified\b/i.test(tags) ? true : null) : null);
  const deviceRaw = str(pick(f, ["Device Type", "device_type", "device"]));
  const device = deviceRaw === "D" ? "desktop" : deviceRaw === "M" ? "mobile" : deviceRaw;
  const startedUtc = pick(f, ["Start Time", "start_time", "startTime", "started_at", "call_start", "created_at", "date_time", "datetime", "timestamp"]);
  const startedLocal = pick(f, ["Start Time (local timezone)", "start_time_local_timezone", "start_time_local", "local_start_time"]);

  const row: CallRow = {
    nimbata_call_id: id,
    started_at: ts(startedUtc, false) ?? ts(startedLocal, true),
    ended_at: ts(pick(f, ["End Time", "end_time", "endTime", "ended_at"]), false),
    caller_number: caller,
    caller_phone_e164: toE164AU(caller),
    tracking_number: str(pick(f, ["Tracking Number (international)", "tracking_number_international", "Tracking Number", "tracking_number", "trackingNumber", "to", "dialed_number"])),
    tracking_number_name: str(pick(f, ["Tracking Number Friendly Name", "tracking_number_friendly_name", "tracking_number_name"])),
    destination_number: str(pick(f, ["Destination Number (international)", "destination_number_international", "Destination Number", "destination_number", "forward_to"])),
    call_status: statusRaw,
    answered,
    missed: answered === null ? null : !answered,
    duration_seconds: int(pick(f, ["Call Duration", "call_duration", "duration", "duration_seconds", "callDuration"])),
    talk_duration_seconds: talk,
    call_frequency: freq,
    first_time_caller: first,
    repeat_caller: first === null ? null : !first,
    tracking_source: str(pick(f, ["Configured Tracking Source", "configured_tracking_source", "tracking_source", "trackingSource", "channel"])),
    source: str(pick(f, ["source", "traffic_source", "session_source"])),
    medium: str(pick(f, ["medium", "traffic_medium", "session_medium"])),
    campaign: str(pick(f, ["campaign", "campaign_name", "campaignName", "google_ads_campaign"])),
    campaign_id: str(pick(f, ["campaign_id", "campaignId"])),
    keyword: str(pick(f, ["keyword", "search_keyword", "google_ads_keyword"])),
    match_type: str(pick(f, ["match_type", "matchType", "keyword_match_type"])),
    device,
    landing_page: str(pick(f, ["Landing Page", "landing_page", "landingPage"])),
    action_page: str(pick(f, ["Action Page (Call page)", "action_page_call_page", "action_page", "call_page", "actionPage"])),
    referrer: str(pick(f, ["referrer", "referer", "referrer_url", "referring_url"])),
    gclid: str(pick(f, ["Google Ads Click ID", "google_ads_click_id", "gclid", "gbraid", "wbraid"])),
    fbclid: str(pick(f, ["Facebook Click ID", "facebook_click_id", "fbclid"])),
    msclkid: str(pick(f, ["Microsoft Click ID", "microsoft_click_id", "msclkid"])),
    ga_session_id: str(pick(f, ["GA Session ID", "ga_session_id"])),
    utm_source: str(pick(f, ["UTM Source", "utm_source", "utmSource"])),
    utm_medium: str(pick(f, ["UTM Medium", "utm_medium", "utmMedium"])),
    utm_campaign: str(pick(f, ["UTM Campaign", "utm_campaign", "utmCampaign"])),
    utm_term: str(pick(f, ["UTM Term", "utm_term", "utmTerm"])),
    utm_content: str(pick(f, ["UTM Content", "utm_content", "utmContent"])),
    call_tag: tags,
    call_outcome: str(pick(f, ["lead_outcome", "business_outcome", "disposition", "call_result", "conversion_status", "outcome"])),
    qualified_lead: qualified,
    call_value: num(pick(f, ["Value", "value", "call_value", "callValue", "revenue", "conversion_value"])),
    has_recording: bool(pick(f, ["Has Recording", "has_recording", "hasRecording"])),
    recording_url: url(pick(f, ["Rec Link", "rec_link", "recording_url", "recordingUrl", "recording"])),
    transcription_url: url(pick(f, ["Transcription", "transcription_url", "transcriptionUrl", "transcription"])),
    notes: str(pick(f, ["notes", "note", "comment", "comments"])),
    raw_payload: payload,
    is_test: TEST_RE.test(id) || TEST_RE.test(String(pick(f, ["Caller Name", "caller_name"]) ?? "")) || bool(pick(f, ["test", "is_test", "sample"])) === true,
  };
  return { row, fields };
}

// Strip values that look like credentials before anything is logged.
export function safeFieldList(fields: string[]): string {
  return fields.filter((k) => !/token|secret|password|auth|key/i.test(k)).join(", ").slice(0, 400);
}

export function melbourneToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: MEL, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export function addDays(iso: string, n: number): string {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function callDayMelbourne(utcIso: string | null): string | null {
  if (!utcIso) return null;
  return new Intl.DateTimeFormat("en-CA", { timeZone: MEL, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(utcIso));
}
