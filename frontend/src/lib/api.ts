// Accès à l'API Python (/api/...). Les types décrivent exactement ce que renvoie app/web/api.py :
// si l'un change, TypeScript signale les écrans à adapter au moment de la compilation.
import { accessToken, AUTH_LOST } from "@/lib/auth";

export type Counters = { today: number; last_hour: number; daily_cap: number; hourly_cap: number };

export type Status = {
  version: string;
  now: string;
  timezone: string;
  test_mode: boolean;
  test_mode_locked: boolean;
  mailbox: { configured: boolean; email: string | null; display_name: string | null };
  engine: { running: boolean; last_tick: string | null; error: string | null };
  sync: { last_ok: string | null; last_attempt: string | null; error: string | null; interval_minutes: number };
  counters: Counters | null;
  next_send_at: string | null;
  to_classify: number;
};

export type UpdateStatus = { current: string; url: string; checked_at: string | null; available: string | null; error: string | null; newer: boolean };
export type UpdateReport = { version: string; written: number; deferred: string[]; restarting: boolean };
export type Backups = { items: { name: string; date: string; label: string; size: number }[]; copy_dir: string; copy_dir_ok: boolean; copies: number; last_copy: string | null };
export type GuideKey = "mailbox" | "signature" | "test" | "contacts" | "real";
export type GuideProgress = { steps: Record<GuideKey, boolean>; done: number; total: number };

export type ContactRef = {
  id: number;
  first_name: string | null;
  last_name: string | null;
  email: string;
  company: string | null;
  sequence_code: string | null;
  phone: string | null;
};

export type Row = { key: string; reached: number; replies: number; rate: number | null };

export type Dashboard = {
  has_contacts: boolean;
  followups: { count: number; days: number };
  indicators: {
    enrolled: number;
    reached: number;
    sent_total: number;
    sent_by_step: Record<string, number>;
    replies: number;
    reply_rate: number | null;
    interested: number;
    bounced: number;
    unsubscribed: number;
    out_of_office: number;
    completed_no_reply: number;
  };
  segments: Row[];
  ab: { rows: Row[]; too_small: boolean; min_sample: number };
  campaigns: {
    id: number;
    name: string;
    status: "active" | "paused";
    enrolled: number;
    reached: number;
    replies: number;
    reply_rate: number | null;
    completed: number;
  }[];
  callbacks: { message_id: number; callback_on: string; note: string | null; contact: ContactRef }[];
  to_review: {
    enrollment_id: number;
    status: "needs_review" | "error";
    step: number;
    error: string | null;
    contact: ContactRef;
    campaign: { id: number; name: string };
  }[];
  unmatched: { id: number; subject: string; excerpt: string; received_at: string; suggestion: ContactRef | null }[];
  queue: { enrollment_id: number; due_at: string; step: number; contact: ContactRef; campaign: { id: number; name: string } }[];
};

export type SyncResult = { ok: boolean; error: string | null; counts: Record<string, number> };

// ----------------------------------------------------------------- contacts
export type ContactRow = ContactRef & {
  /** V3 : employé qui suit ce contact (prospects) ; null = libre. */
  owner?: { id: number; name: string; me: boolean } | null;
  job_title: string | null;
  wave: string | null;
  status: "active" | "replied" | "bounced" | "unsubscribed" | "do_not_contact";
  reliability: string;
  sector_family: string | null;
  target_segment: string | null;
  kind: Kind;
  company_id: number | null;
  department: Department | null;
  seniority: Seniority | null;
};
export type Department = "souscription" | "gestion" | "production" | "maritime_transport" | "autre";
export type Seniority = "junior" | "senior" | "directeur";
export type Attachment = { id: number; name: string; size: number; type: string; token?: string };
// V2.25 : l'aperçu exact avant l'envoi d'une séquence
export type SendPayload = { contact_ids: number[]; overlap?: boolean; overrides?: Record<string, unknown>; fills?: Record<string, string>; attachment_ids?: number[]; max_steps?: number | null };
export type ReviewEmail = { position: number; subject: string; body: string; planned_at: string | null; same_thread: boolean; problems: string[]; warnings: string[]; attachments: Attachment[] };
export type ReviewPerson = { contact: ContactRef; to: string; refused: string | null; problems: string[]; overlap: unknown[]; emails: ReviewEmail[] };
export type SequenceReview = { sequence: { id: number; name: string }; steps: number; total_steps: number; ab_subjects: boolean; test_mode: boolean;
  from: { name: string; email: string } | null; people: ReviewPerson[] };
/** V3 : prochains envois d'une campagne, rendus comme par le moteur. */
export type CampaignUpcoming = { total: number; test_mode: boolean; campaign_status: string; from: { name: string; email: string } | null;
  items: { enrollment_id: number; contact: ContactRef; to: string; status: string; variant: string | null; emails: ReviewEmail[] }[] };
export type SequenceCategory = "prospection" | "gestion" | "souscription";
export type Kind = "prospect" | "client" | "insurer" | "partner";
export type CompanySummary = {
  id: number; name: string; kind: Kind; domain: string | null; sector: string | null; website: string | null;
  phone: string | null; people: number; logo: string | null;
};
export type CompanyList = { items: CompanySummary[]; kinds: (Option & { count: number })[]; total: number };
export type CompanyDetail = CompanySummary & {
  notes: string;
  created_at: string;
  people: (ContactRef & { job_title: string | null; status: ContactRow["status"]; kind: Kind; campaign: string | null;
    department: Department | null; seniority: Seniority | null })[];
  activity: { id: number; direction: "in" | "out"; kind: string | null; subject: string; ts: string; contact: ContactRef; attachments: string[] }[];
};
export type CompanyInput = Partial<Pick<CompanyDetail, "name" | "kind" | "domain" | "website" | "phone" | "sector" | "notes">>;
export type Option = { value: string; label: string };
export type MailPerson = ContactRef & { kind: Kind; status: ContactRow["status"]; company_ref: { id: number; name: string } | null };
export type MailItem = {
  uid: number; from_name: string; from_email: string; to: string[]; subject: string; date: string | null; seen: boolean;
  message_id: string | null; has_attachments: boolean; size: number | null;
  contact: MailPerson | null; campaign_reply: { id: number; kind: string; classification: string | null } | null;
};
export type AwaitingItem = MailItem & { folder: string; business_days: number };
export type Awaiting = { days: number; items: AwaitingItem[]; window_days: number; fetched_at: string; sent_folder: string | null };
export type MailList = { folder: string; days: number; items: MailItem[]; found: number; truncated: boolean; fetched_at: string };
export type MailMessage = Omit<MailItem, "seen" | "has_attachments" | "size"> & {
  folder: string; cc: string[]; references: string[]; kind: string; text: string; full: string;
  attachments: MailAttachment[];
  html: string | null; remote_images: boolean;
};
export type MailAttachment = { index: number; name: string; size: number; type: string; inline: boolean; viewable: boolean; url: string;
  previewable?: boolean };
/** V3 : aperçu d'une pièce jointe (PDF, image, Word, Excel, CSV, texte). */
export type AttachmentPreview = { name: string; type: string; size: number; kind: "pdf" | "image" | "html" | "text" | "none";
  html?: string; text?: string; truncated?: boolean; reason?: string };
export type MailFolders = { items: { raw: string; display: string; label: string; rank: number }[]; sent: string | null; watched: string[] };
export type MailDraft = {
  to: string; cc?: string; subject: string; body: string; in_reply_to?: string | null; references?: string[];
  signature?: boolean; force?: boolean; attachment_ids?: number[];
};
export type ContactList = {
  total: number;
  items: ContactRow[];
  options: {
    target_segment: string[];
    sector_family: string[];
    sequence_code: string[];
    wave: string[];
    reliability: string[];
    status: Option[];
    campaigns: Option[];
    department: string[];
    seniority: string[];
    companies_by_kind: Partial<Record<Kind, Option[]>>;
  };
  vocab: Vocab;
  companies: string[];
  company_kinds: Record<string, Kind>;
  kind_counts: Partial<Record<Kind, number>>;
};
export type Vocab = {
  targets: (Option & { code: string })[];
  sectors: (Option & { code: string })[];
  sizes: string[];
  waves: string[];
  reliability: string[];
  kinds: Option[];
  departments: Option[];
  seniorities: Option[];
};
export type ContactInput = Partial<Record<
  "first_name" | "last_name" | "email" | "job_title" | "company" | "phone" | "website" | "linkedin_url" | "sector" |
  "target_segment" | "sector_family" | "size_bucket" | "wave" | "email_reliability" | "notes" | "kind" | "department" | "seniority", string>> & { custom?: Record<string, string> };
export type Followup = {
  contact: ContactRef & { job_title: string | null };
  last_sent: string;
  business_days: number;
  step: number | null;
  subject: string;
  campaign: { id: number; name: string } | null;
  next_due_at: string | null;
  next_step?: number | null;  // V2.25.1 : n° de l'email automatique prévu (2 = relance 1)
  next_campaign?: { id: number; name: string } | null;
  message: { id: number; message_id: string | null; body: string; references: string[]; test_mode: boolean } | null;
  days: number;
};
export type ContactDetail = ContactRow & {
  company_ref: { id: number; name: string; kind: Kind } | null;
  sector: string | null;
  size_bucket: string | null;
  website: string | null;
  linkedin_url: string | null;
  email_reliability_detail: string | null;
  source: string | null;
  notes: string;
  custom: { key: string; label: string; value: string }[];
  suppressed: boolean;
  status_label: string;
  enrollments: { id: number; campaign: { id: number; name: string }; status: string; step: number; next_due_at: string | null; active: boolean }[];
  timeline: { ts: string; kind: "out" | "in" | "event"; title: string; detail: string }[];
};
export type ImportColumns = {
  token: string;
  filename: string;
  sheets: string[];
  sheet: string | null;
  header_row: number;
  rows: number;
  columns: { index: number; header: string; mapping: string; custom: string; samples: string[] }[];
  fields: Option[];
};
export type ImportRow = { row: number; email: string | null; reason: string; warnings: string[] };
export type ImportPreview = { new: number; update: number; ignored: ImportRow[]; suppressed: ImportRow[]; warnings: ImportRow[] };
export type Exclusion = { id: number; value: string; reason: string; created_at: string; kind: "email" | "domain" | "hash"; removable: boolean };

// ----------------------------------------------------------------- séquences
export type StepData = {
  id: number;
  position: number;
  delay_days: number;
  business_days: boolean;
  weekday: number | null;     // 0 = lundi … 4 = vendredi (V2.5)
  send_time: string | null;   // « 10:00 »
  same_thread: boolean;
  body: string;
  subject_a: string;
  subject_b: string;
  attachments: Attachment[];  // V2.8
};
export type SequenceData = { id: number; name: string; category: SequenceCategory; branch?: string | null; campaigns: number; steps: StepData[];
  shared?: boolean; editable?: boolean };
export type SequenceFull = SequenceData & { variables: string[]; custom_fields: string[] };
export type SequenceList = {
  todo_blocks: string[];
  items: { id: number; name: string; category: SequenceCategory; branch?: string | null; steps: number; campaigns: number; created_at: string; total_days: number }[];
  categories: Option[];
};
export type PreviewStep = {
  position: number;
  subject: string;
  body: string;
  planned_at: string | null;
  same_thread: boolean;
  problems: string[];
  warnings: string[];
};
export type Preview = { contact: ContactRef | null; labels: string[]; variant: string | null; steps: PreviewStep[] };
export type Block = { id: number; kind: "target" | "sector"; key: string; label: string; body: string; todo: boolean; custom: boolean; used: number };
export type SequenceTemplate = { subject: string; body: string; contact: ContactRef | null; attachments: Attachment[] };
export type SequenceDraft = {
  sequence: { id: number; name: string; category: SequenceCategory };
  contact: ContactRef; kind: Kind;
  steps: { position: number; own_subject: boolean; subject: string; body: string; delay_days: number; problems: string[] }[];
  attachments: Attachment[];
};
export type SendResult = {
  campaign: { id: number; name: string; status: string };
  sent: { contact: ContactRef; next_due_at: string | null }[];
  refused: { contact: ContactRef; reason: string; problems: string[]; overlap: string[] }[];
};

// ----------------------------------------------------------------- campagnes
export type Indicators = Dashboard["indicators"];
export type CampaignListItem = {
  id: number;
  name: string;
  status: "draft" | "active" | "paused" | "finished";
  sequence: string | null;
  direct: boolean;
  filters: Record<string, string>;
  created_at: string;
  activated_at: string | null;
  start_at: string | null;
  counts: Record<string, number>;
  indicators: Indicators;
};
export type Candidate = ContactRef & { excluded: string | null; other_campaigns: string[]; problems?: string[]; problem_count?: number };
export type CampaignDetail = {
  id: number;
  name: string;
  status: CampaignListItem["status"];
  direct: boolean;
  filters: Record<string, string>;
  stop_on_domain_reply: boolean;
  activated_at: string | null;
  start_at: string | null;
  sequence: { id: number; name: string; steps: number } | null;
  counts: Record<string, number>;
  indicators: Indicators;
  segments: Row[];
  ab: Dashboard["ab"];
  candidates: Candidate[];
  enrollments: { id: number; status: string; status_label: string; variant: string | null; step: number; max_steps?: number | null; next_due_at: string | null; error: string | null; contact: ContactRef }[];
  started: boolean;
};
export type Activation = {
  eligible: number;
  excluded: Candidate[];
  overlapping: Candidate[];
  with_problems: Candidate[];
  with_problems_count: number;
  reliability_ratio: number;
  reliability_warn: boolean;
  link_warnings: string[];
  first_send: string | null;
  last_send: string | null;
  test_mode: boolean;
  blocked: boolean;
};

// ------------------------------------------------------------------ réponses
export type Reply = {
  id: number;
  kind: string;
  subject: string;
  text: string;
  full: string | null;
  received_at: string;
  classification: string | null;
  callback_on: string | null;
  note: string | null;
  return_date: string | null;
  test_mode: boolean;
  contact: ContactRef;
  message_id: string | null;
  references: string[];
};
export type Replies = {
  filter: string;
  filters: { key: string; label: string; count: number }[];
  classes: { key: string; label: string }[];
  items: Reply[];
  unmatched: { id: number; subject: string; text: string; received_at: string; suggestion: ContactRef | null }[];
};
export type Journal = {
  entities: Option[];
  items: { id: number; ts: string; level: string; entity: string | null; entity_id: number | null; text: string }[];
};
export type Activity = { day: string; sent: number; replies: number }[];

// ------------------------------------------------------------------ agenda, notifications (V2.8)
export type ReminderKind = "call" | "email" | "quote" | "meeting" | "renewal" | "other";
export type ReminderItem = {
  id: number; source: "reminder" | "callback"; kind: ReminderKind; kind_label: string; title: string; notes: string;
  due_on: string; due_time: string | null; done: boolean; done_at: string | null; created_at: string | null;
  contact: ContactRef | null; company: { id: number; name: string; kind: Kind } | null;
};
export type ReminderList = { items: ReminderItem[]; kinds: Option[]; today: string };
export type ReminderInput = {
  kind?: ReminderKind; title?: string; notes?: string; due_on?: string; due_time?: string | null;
  contact_id?: number | null; company_id?: number | null; done?: boolean;
};
export type Notification = {
  key: string; type: "reminder" | "callback" | "followup" | "replies" | "error" | "update"; level: "info" | "warning" | "error";
  title: string; detail: string; href: string; at: string | null; seen: boolean; reminder_id?: number;
};

// ------------------------------------------------------------------ réglages
export type MailboxSettings = {
  display_name: string;
  email: string;
  smtp_host: string;
  smtp_port: number;
  smtp_security: "ssl" | "starttls";
  imap_host: string;
  imap_port: number;
  username: string;
  sent_folder: string | null;
  watched_folders: string[];
  signature: string;
};
export type SendingSettings = {
  send_days: number[];
  send_windows: [string, string][];
  holidays: { date: string; label: string }[];
  daily_cap: number;
  hourly_cap: number;
  min_gap_s: number;
  max_gap_s: number;
  rampup_enabled: boolean;
  rampup_per_day: number;
  unsubscribe_line: string;
  unsubscribe_enabled: boolean;
  digest_time: string;
  digest_recipient: string;
  auto_reply_continues: boolean;
  followup_days: number;
};
export type Settings = {
  mailbox: MailboxSettings;
  mailbox_exists: boolean;
  has_password: boolean;
  folders: { raw: string; display: string }[];
  sending: SendingSettings;
  test_mode: boolean;
  test_mode_locked: boolean;
  cap_warning: number;
};
export type ConnectionReport = {
  ok: boolean;
  steps: { label: string; ok: boolean; detail: string }[];
  folders: { raw: string; display: string }[];
  sent_folder: string | null;
  junk_folder: string | null;
};

/** Erreur renvoyée par l'API : message lisible + éventuelles erreurs par champ de formulaire. */
export class ApiError extends Error {
  fields: Record<string, string>;
  status: number;
  existingId: number | null;
  data: { problems?: string[]; overlap?: string[]; confirm?: boolean };
  constructor(message: string, status: number, fields: Record<string, string> = {}, existingId: number | null = null,
    data: { problems?: string[]; overlap?: string[]; confirm?: boolean } = {}) {
    super(message);
    this.data = data;
    this.status = status;
    this.fields = fields;
    this.existingId = existingId;
  }
}

/** V3 : un employé (compte de connexion). */
export type TeamUser = {
  id: number; email: string; full_name: string; role: "admin" | "user"; active: boolean; linked: boolean;
  last_seen_at: string | null; mailbox: string | null; contacts: number;
};
export type Me = (TeamUser & { server_mode: true }) | { id: null; role: "admin"; server_mode: false };

async function request<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const token = await accessToken(); // V3 : employé connecté (null sur le poste unique)
  const res = await fetch(path, {
    ...rest,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    headers: { Accept: "application/json", ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(rest.headers || {}) },
  });
  if (res.status === 401 && token) window.dispatchEvent(new Event(AUTH_LOST));
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* réponse sans JSON */
    }
    if (detail && typeof detail === "object" && "errors" in (detail as object)) {
      const d = detail as { errors: Record<string, string>; existing_id?: number };
      throw new ApiError(Object.values(d.errors).join(" "), res.status, d.errors, d.existing_id ?? null);
    }
    if (detail && typeof detail === "object" && "message" in (detail as object)) {
      const d = detail as { message: string; problems?: string[]; overlap?: string[]; confirm?: boolean };
      throw new ApiError(d.message, res.status, {}, null, d);
    }
    throw new ApiError(typeof detail === "string" ? detail : `Erreur ${res.status}`, res.status);
  }
  return res.json() as Promise<T>;
}

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && p.set(k, String(v)));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  status: () => request<Status>("/api/status"),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  guide: () => request<GuideProgress>("/api/guide"),
  update: () => request<UpdateStatus>("/api/update"),
  backups: () => request<Backups>("/api/backups"),
  backupNow: () => request<Backups>("/api/backups/now", { method: "POST" }),
  backupCopyDir: (path: string) => request<Backups>("/api/backups/copy-dir", { method: "POST", json: { path } }),
  updateUrl: (url: string) => request<UpdateStatus>("/api/update/url", { method: "POST", json: { url } }),
  updateCheck: () => request<UpdateStatus>("/api/update/check", { method: "POST" }),
  updateInstall: () => request<UpdateReport>("/api/update/install", { method: "POST" }),
  guideCheck: (key: GuideKey, done: boolean) => request<GuideProgress>("/api/guide", { method: "POST", json: { key, done } }),
  activity: (days = 30) => request<Activity>(`/api/activity?days=${days}`),
  sync: () => request<SyncResult>("/api/sync", { method: "POST" }),
  confirmSent: (id: number) => request<{ ok: boolean }>(`/api/enrollments/${id}/confirm-sent`, { method: "POST" }),
  retry: (id: number) => request<{ ok: boolean }>(`/api/enrollments/${id}/retry`, { method: "POST" }),
  sendNow: (id: number) => request<{ detail: string }>(`/api/enrollments/${id}/send-now`, { method: "POST" }),
  skip: (id: number) => request<{ skipped: number }>(`/api/enrollments/${id}/skip`, { method: "POST" }),
  callbackDone: (id: number) => request<{ ok: boolean }>(`/api/callbacks/${id}/done`, { method: "POST" }),

  contacts: (f: Record<string, string>) => request<ContactList>(`/api/contacts${qs(f)}`),
  contactsCount: (f: Record<string, string>) => request<{ matching: number; active: number; protected: number }>(`/api/contacts/count${qs(f)}`),
  contact: (id: number) => request<ContactDetail>(`/api/contacts/${id}`),
  contactsSetOwner: (contact_ids: number[], owner_id: number | null) =>
    request<{ updated: number }>("/api/contacts/owner", { method: "POST", json: { contact_ids, owner_id } }),
  contactCreate: (body: ContactInput) => request<{ id: number; warnings: string[] }>("/api/contacts", { method: "POST", json: body }),
  contactUpdate: (id: number, body: ContactInput) => request<{ changed: string[] }>(`/api/contacts/${id}`, { method: "PUT", json: body }),
  followups: () => request<Followup[]>("/api/followups"),
  awaitingDismiss: (items: { from_email: string; date: string | null }[]) =>
    request<{ dismissed: number }>("/api/mailbox/awaiting/dismiss", { method: "POST", json: { items } }),
  awaitingRestore: (senders: string[]) => request("/api/mailbox/awaiting/restore", { method: "POST", json: { senders } }),
  mailsWith: (email: string) => request<{ items: { folder: string; uid: number; subject: string; date: string | null; direction: "in" | "out"; has_attachments: boolean }[]; days: number }>(`/api/mailbox/with${qs({ email })}`),
  awaiting: (refresh = false) => request<Awaiting>(`/api/mailbox/awaiting${qs({ refresh: refresh || undefined })}`),
  contactNotes: (id: number, notes: string) => request(`/api/contacts/${id}/notes`, { method: "PUT", json: { notes } }),
  contactAction: (id: number, action: "do-not-contact" | "reactivate") => request(`/api/contacts/${id}/${action}`, { method: "POST" }),
  contactErase: (id: number, confirm: string) => request(`/api/contacts/${id}/erase`, { method: "POST", json: { confirm } }),
  removeEnrollment: (cid: number, eid: number) => request(`/api/contacts/${cid}/enrollments/${eid}/remove`, { method: "POST" }),
  companies: (f: { q?: string; kind?: string } = {}) => request<CompanyList>(`/api/companies${qs(f)}`),
  company: (id: number) => request<CompanyDetail>(`/api/companies/${id}`),
  companyCreate: (body: CompanyInput) => request<{ id: number }>("/api/companies", { method: "POST", json: body }),
  companyUpdate: (id: number, body: CompanyInput) => request<{ stopped: number }>(`/api/companies/${id}`, { method: "PUT", json: body }),
  companyMerge: (id: number, intoId: number) => request<{ moved: number; id: number }>(`/api/companies/${id}/merge`, { method: "POST", json: { into_id: intoId } }),
  companyDelete: (id: number) => request<{ ok: boolean }>(`/api/companies/${id}`, { method: "DELETE" }),
  openCampaigns: () => request<{ id: number; name: string; status: string; category: SequenceCategory }[]>("/api/campaigns-open"),
  enroll: (campaignId: number, contactId: number, overlap = false) =>
    request<{ id: number; variant: string | null; paused: boolean }>(`/api/campaigns/${campaignId}/enroll`, { method: "POST", json: { contact_id: contactId, overlap } }),
  mailFolders: () => request<MailFolders>("/api/mailbox/folders"),
  mailList: (folder: string, days: number, refresh = false) => request<MailList>(`/api/mailbox/messages${qs({ folder, days, refresh: refresh || undefined })}`),
  mailForward: (folder: string, uid: number) => request<{ attachments: Attachment[]; skipped: string[] }>(`/api/mailbox/messages/${uid}/forward${qs({ folder })}`, { method: "POST" }),
  mailArchive: (folder: string, uid: number) => request<{ archive_folder: string; message_id: string }>(`/api/mailbox/messages/${uid}/archive${qs({ folder })}`, { method: "POST" }),
  mailUnarchive: (message_id: string, folder: string, kind: "archive" | "junk" = "archive") =>
    request<{ ok: boolean }>("/api/mailbox/unarchive", { method: "POST", json: { message_id, folder, kind } }),
  mailSpam: (folder: string, uid: number) => request<{ archive_folder: string; message_id: string }>(`/api/mailbox/messages/${uid}/spam${qs({ folder })}`, { method: "POST" }),
  campaignUpcoming: (id: number, enrollmentId?: number) =>
    request<CampaignUpcoming>(`/api/campaigns/${id}/upcoming${enrollmentId ? `?enrollment_id=${enrollmentId}` : ""}`),
  mailPreview: (partUrl: string) => request<AttachmentPreview>(partUrl.replace("/part/", "/preview/")),
  mailMessage: (folder: string, uid: number) => request<MailMessage>(`/api/mailbox/messages/${uid}${qs({ folder })}`),
  mailSend: (d: MailDraft) => request<{ id: number; test_mode: boolean; to: string }>("/api/mailbox/send", { method: "POST", json: d }),
  picker: (q: string) => request<(ContactRef & { job_title?: string | null })[]>(`/api/contacts-picker${qs({ q })}`),

  importUpload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<ImportColumns>("/api/import", { method: "POST", body: fd });
  },
  importColumns: (token: string, sheet: string) => request<ImportColumns>(`/api/import/${token}${qs({ sheet })}`),
  importPreview: (token: string, sheet: string | null, mapping: string[]) =>
    request<ImportPreview>(`/api/import/${token}/preview`, { method: "POST", json: { sheet, mapping } }),
  importCommit: (token: string, sheet: string | null, mapping: string[]) =>
    request<{ new: number; update: number; ignore: number }>(`/api/import/${token}/commit`, { method: "POST", json: { sheet, mapping } }),
  importCancel: (token: string) => request(`/api/import/${token}`, { method: "DELETE" }),
  exclusions: () => request<Exclusion[]>("/api/exclusions"),
  exclusionAdd: (entry: string, note: string) =>
    request<{ entry: string; added: boolean; affected: number }>("/api/exclusions", { method: "POST", json: { entry, note } }),
  exclusionDelete: (id: number) => request(`/api/exclusions/${id}`, { method: "DELETE" }),

  sequences: () => request<SequenceList>("/api/sequences"),
  sequenceCreate: (name: string, category: SequenceCategory = "prospection", steps = 3) =>
    request<{ id: number }>("/api/sequences", { method: "POST", json: { name, category, steps } }),
  sequenceDuplicate: (id: number) => request<{ id: number }>(`/api/sequences/${id}/duplicate`, { method: "POST" }),
  sequence: (id: number) => request<SequenceFull>(`/api/sequences/${id}`),
  sequenceSave: (id: number, name: string, steps: StepData[], category?: SequenceCategory, branch?: string | null) =>
    request<SequenceData>(`/api/sequences/${id}`, {
      method: "PUT", json: { name, category, branch: branch ?? "", steps: steps.map((s) => ({ ...s, attachment_ids: s.attachments.map((a) => a.id) })) },
    }),
  sequenceDelete: (id: number) => request(`/api/sequences/${id}`, { method: "DELETE" }),
  stepAdd: (id: number) => request<SequenceData>(`/api/sequences/${id}/steps`, { method: "POST" }),
  stepDelete: (id: number, stepId: number) => request<SequenceData>(`/api/sequences/${id}/steps/${stepId}`, { method: "DELETE" }),
  preview: (id: number, contactId?: number, variant?: string) =>
    request<Preview>(`/api/sequences/${id}/preview${qs({ contact_id: contactId, variant })}`),
  previewSend: (id: number, contactId: number, variant: string) =>
    request<{ sent: number; to: string }>(`/api/sequences/${id}/preview/send`, { method: "POST", json: { contact_id: contactId, variant } }),
  blocks: () => request<Block[]>("/api/blocks"),
  blockSave: (id: number, body: string) => request<{ id: number; todo: boolean }>(`/api/blocks/${id}`, { method: "PUT", json: { body } }),
  blockCreate: (kind: Block["kind"], label: string) => request<Block>("/api/blocks", { method: "POST", json: { kind, label } }),
  blockDelete: (id: number) => request(`/api/blocks/${id}`, { method: "DELETE" }),
  sequenceSchedule: (id: number) => request<{ position: number; planned_at: string | null }[]>(`/api/sequences/${id}/schedule`),
  sequenceTemplate: (id: number, email: string) => request<SequenceTemplate>(`/api/sequences/${id}/template${qs({ email })}`),
  sequenceDraft: (id: number, contactId: number) => request<SequenceDraft>(`/api/sequences/${id}/draft${qs({ contact_id: contactId })}`),
  sequenceSend: (id: number, contactIds: number[], overlap = false, overrides?: Record<string, { subject?: string; body?: string }>,
                 shared?: { fills: Record<string, string>; attachment_ids: number[] }, maxSteps?: number | null) =>
    request<SendResult>(`/api/sequences/${id}/send`, { method: "POST", json: { contact_ids: contactIds, overlap, overrides, ...(shared ?? {}), max_steps: maxSteps ?? null } }),
  sequenceReview: (id: number, body: SendPayload) => request<SequenceReview>(`/api/sequences/${id}/review`, { method: "POST", json: body }),
  sequenceHoles: (id: number, steps?: number | null) => request<{ holes: string[] }>(`/api/sequences/${id}/holes${qs({ steps: steps ?? undefined })}`),

  campaigns: () => request<CampaignListItem[]>("/api/campaigns"),
  campaignStart: (id: number, startAt: string | null) =>
    request<{ moved: number; start_at: string | null }>(`/api/campaigns/${id}/start`, { method: "PUT", json: { start_at: startAt } }),
  campaignCreate: (body: { name: string; sequence_id: number; filters: Record<string, string>; stop_on_domain_reply: boolean; start_at?: string | null }) =>
    request<{ id: number }>("/api/campaigns", { method: "POST", json: body }),
  campaign: (id: number) => request<CampaignDetail>(`/api/campaigns/${id}`),
  activation: (id: number, overlap: boolean) => request<Activation>(`/api/campaigns/${id}/activation${qs({ overlap })}`),
  activate: (id: number, overlap: boolean) => request<{ enrolled: number }>(`/api/campaigns/${id}/activate`, { method: "POST", json: { overlap } }),
  campaignAction: (id: number, action: "pause" | "resume" | "delete") => request(`/api/campaigns/${id}/${action}`, { method: "POST" }),

  replies: (f: string) => request<Replies>(`/api/replies${qs({ f })}`),
  classify: (id: number, classification: string, callback_on?: string, note?: string) =>
    request<Reply>(`/api/replies/${id}/classify`, { method: "POST", json: { classification, callback_on, note } }),
  replyNote: (id: number, note: string) => request(`/api/replies/${id}/note`, { method: "PUT", json: { note } }),
  attach: (id: number, contactId: number) => request(`/api/replies/${id}/attach`, { method: "POST", json: { contact_id: contactId } }),
  dismiss: (id: number) => request(`/api/replies/${id}/dismiss`, { method: "POST" }),

  journal: (f: { entity?: string; level?: string; q?: string }) => request<Journal>(`/api/journal${qs(f)}`),

  settings: () => request<Settings>("/api/settings"),
  saveMailbox: (body: MailboxSettings & { password?: string }) => request("/api/settings/mailbox", { method: "PUT", json: body }),
  saveSending: (body: SendingSettings) => request("/api/settings/sending", { method: "PUT", json: body }),
  setTestMode: (enabled: boolean) => request<{ test_mode: boolean }>("/api/settings/test-mode", { method: "PUT", json: { enabled } }),
  uploadAttachment: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<Attachment>("/api/attachments", { method: "POST", body: fd });
  },
  companyLogo: (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ logo: string }>(`/api/companies/${id}/logo`, { method: "POST", body: fd });
  },
  companyLogoDelete: (id: number) => request(`/api/companies/${id}/logo`, { method: "DELETE" }),
  reminders: (f: { start?: string; end?: string; contact_id?: number; company_id?: number; include_done?: boolean } = {}) =>
    request<ReminderList>(`/api/reminders${qs(f)}`),
  reminderCreate: (body: ReminderInput) => request<ReminderItem>("/api/reminders", { method: "POST", json: body }),
  reminderUpdate: (id: number, body: ReminderInput) => request<ReminderItem>(`/api/reminders/${id}`, { method: "PUT", json: body }),
  reminderDelete: (id: number) => request(`/api/reminders/${id}`, { method: "DELETE" }),
  notifications: () => request<{ items: Notification[]; unseen: number }>("/api/notifications"),
  notificationsSeen: (keys?: string[]) => request("/api/notifications/seen", { method: "POST", json: keys ? { keys } : {} }),

  me: () => request<Me>("/api/me"),
  team: () => request<TeamUser[]>("/api/admin/users"),
  teamInvite: (body: { email: string; full_name: string; role: "admin" | "user" }) =>
    request<TeamUser & { invite_error: string | null }>("/api/admin/users", { method: "POST", json: body }),
  teamUpdate: (id: number, body: { full_name?: string; role?: "admin" | "user"; active?: boolean }) =>
    request<TeamUser>(`/api/admin/users/${id}`, { method: "PATCH", json: body }),
  importV2: (file: File, replace = false) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<{ counts: Record<string, number>; files: number; mailbox: string | null }>(
      `/api/admin/import-v2${replace ? "?replace=true" : ""}`, { method: "POST", body: fd });
  },
  teamResend: (id: number) => request<{ invite_error: string | null }>(`/api/admin/users/${id}/resend`, { method: "POST" }),

  testConnection: (body: MailboxSettings & { password?: string; send_test_email: boolean }) =>
    request<ConnectionReport>("/api/settings/test-connection", { method: "POST", json: body }),
};
