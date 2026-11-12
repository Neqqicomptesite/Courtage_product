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
  wave: string | null; lot_number?: number | null;
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
export type CampaignSent = { total: number; test_mode: boolean; from: { name: string; email: string } | null;
  items: { id: number; contact: ContactRef | null; to: string; subject: string; body: string; sent_at: string; position: number | null; test_mode: boolean; replied: boolean }[] };
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
export type MailList = { folder: string; days: number; items: MailItem[]; found: number; truncated: boolean; fetched_at: string | null; searched?: boolean; unsearchable?: boolean };
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
export type AddressSuggestion = { email: string; name: string | null; company: string | null; kind: string | null; uses: number; contact_id: number | null };
export type MailDraft = {
  to: string; cc?: string; bcc?: string; subject: string; body: string; in_reply_to?: string | null; references?: string[];
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
export type ContactListItem = { id: number; name: string; count: number; source: "manual" | "import" | "campaign"; shared: boolean;
  owner: string | null; mine: boolean; editable: boolean; created_at: string | null; updated_at: string | null };
export type ImportDone = { new: number; update: number; ignore: number; list?: { id: number; name: string; count: number; prospects: number; lot?: number | null } };

export type ContactDetail = ContactRow & {
  lists?: { id: number; name: string }[];
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
  bounced_at: string | null;
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
  items: { id: number; name: string; category: SequenceCategory; branch?: string | null; steps: number; campaigns: number; created_at: string; total_days: number;
    shared?: boolean; editable?: boolean }[];
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
export type Block = { id: number; kind: "target" | "sector"; key: string; label: string; body: string; todo: boolean; custom: boolean; used: number;
  generic?: boolean; variant_of?: string | null; campaigns?: number };
/** V3.4 : textes d'une campagne : clé de la fiche → texte(s) envoyé(s) (liste = partage A/B). */
export type BlockMap = { target?: Record<string, string | string[]>; sector?: Record<string, string | string[]> };
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
export type Candidate = ContactRef & { excluded: string | null; other_campaigns: string[]; recent?: string | null; problems?: string[]; problem_count?: number };
/** V3.7 : textes par lot (le 4e import ou la 4e recherche → variante 4 : FIN4, BTP4…). */
export type LotText = { kind: "target" | "sector"; root: string; root_label: string; root_id: number; key: string; block_id: number | null };
export type LotTexts = { lot: number; contacts: number; items: LotText[] }[];
export type CampaignDetail = {
  block_map: BlockMap;
  lot_texts?: LotTexts;
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
  no_reply: { count: number; days: number; last_sent: string | null; relaunch_from: string | null } | null;
  enrollments: { id: number; status: string; status_label: string; variant: string | null; step: number; max_steps?: number | null; next_due_at: string | null; error: string | null; contact: ContactRef }[];
  started: boolean;
};
export type Activation = {
  eligible: number;
  excluded: Candidate[];
  overlapping: Candidate[];
  recent: Candidate[];
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
  seen: boolean;
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
  contact: ContactRef | null; company: { id: number; name: string; kind: Kind } | null; quote_case_id?: number | null; contract_id?: number | null;
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


/* ---------------------------------------------------------------- Dossiers de cotation */
export type QuoteStage = "new" | "info" | "consulting" | "partial" | "offers" | "proposed" | "won" | "lost";
export type InsurerStatus = "to_send" | "sent" | "reminded" | "replied" | "offer" | "renegotiate" | "declined";
export type QuoteFileKind = "client" | "current" | "offer" | "other";
export type BranchField = { key: string; label: string; type?: "text" | "number" | "date" | "choice" | "textarea";
  options?: string[]; unit?: string; placeholder?: string; hint?: string; optional?: boolean; branches?: string[] };
export type BranchDef = { name: string; fields: BranchField[]; docs: string[] };
export type QuoteSummary = {
  id: number; ref: string; title: string; branch: string; branches: string[]; branch_label: string; stage: QuoteStage; client_name: string;
  company_id: number | null; contact_id: number | null; owner_id: number | null; owner_name: string | null;
  due_on: string | null; late: boolean; missing: number; insurers: number; insurer_counts: Record<InsurerStatus, number>;
  best_offer: number | null; current_premium: number | null; lost_reason: string | null; created_at: string; updated_at: string;
};
export type QuotePerson = { id: number; email: string; name: string; department: string | null };
export type QuoteRow = {
  id: number; branch: string; status: InsurerStatus; recipients: string[]; sent_at: string | null; replied_at: string | null;
  reminders_sent: number; offer_premium: number | null; offer_rate: string | null; notes: string; last_message_id: string | null;
  next_followup_at: string | null; auto_followups: boolean; sent_by_name: string | null;
};
export type QuoteCompany = { company_id: number; company: string; logo: string | null; contacts: QuotePerson[]; rows: QuoteRow[];
  next_followup_at: string | null; auto_followups: boolean };
export type QuoteMail = { id: number; direction: "out" | "in"; title: string; ts: string; subject: string | null; body: string | null;
  to: string[] | null; cc: string[] | null; from: string | null; attachments: ({ name: string; index: number } | string)[];
  auto: boolean | null; test_mode: boolean | null; insurer_id: number | null; folder: string | null; uid: number | null; mine: boolean };
export type QuoteCompanyEmails = { company_id: number; items: QuoteMail[]; auto_followups: boolean; signature: string;
  upcoming: { n: number; at: string; insurer_ids: number[]; branches: string[]; to: string[]; subject: string; body: string }[] };
export type QuotePreview = { from_name: string; from_email: string; to: string[]; cc: string; subject: string; body: string;
  test_mode: boolean; attachments: string[] };
export type QuoteFileRow = Attachment & { file_id: number; kind: QuoteFileKind; label: string; insurer_id: number | null; created_at: string };
export type QuoteReminder = { id: number; title: string; kind: ReminderKind; due_on: string; due_time: string | null; done: boolean;
  notes: string; mine: boolean; user_name: string | null };
export type QuoteEventRow = {
  id: number; kind: "created" | "stage" | "note" | "fields" | "email_out" | "email_in" | "file" | "insurer" | "edit";
  text: string; insurer_id: number | null; company_id: number | null; user_name: string | null; ts: string;
};
export type ContractLink = { id: number; branch: string; insurer_name: string; end_date: string; status: ContractStatus; policy_number?: string };
export type ContractStatus = "active" | "renewing" | "ended";
export type ContractUrgency = "ok" | "soon" | "urgent" | "past_notice" | "expired" | "ended";
export type Contract = {
  id: number; client_name: string; company_id: number | null; contact: { id: number; name: string } | null;
  insurer_id: number | null; insurer_name: string; branch: string; policy_number: string;
  premium: number | null; rate: string | null; commission_rate: number | null; commission: number | null;
  base_amount: number | null; base_label: string; accessories: number | null; tax_rate: number | null;
  evcat_rate: number | null; evcat_cap: number | null; evcat: number | null; taxes: number | null; ttc: number | null;
  start_date: string | null; end_date: string; notice_days: number; deadline: string; days_to_deadline: number; days_to_end: number;
  tacit: boolean; status: ContractStatus; status_label: string; end_reason: string | null; urgency: ContractUrgency;
  owner: { id: number; name: string } | null; quote_case: { id: number; ref: string } | null;
  renewal_case: { id: number; ref: string; stage: QuoteStage } | null; previous_id: number | null; notes: string;
  history: { ts: string; text: string }[];
};
export type ContractSummary = { active: number; renewing: number; ended: number; premium: number; ttc: number; commission: number;
  past_notice: number; due_30: number; due_60: number; due_90: number; upcoming: number };
export type ContractList = { filter: string; filters: { key: string; label: string }[]; sorts: { key: string; label: string }[];
  summary: ContractSummary; totals: { count: number; premium: number; ttc: number; commission: number }; items: Contract[];
  branches: string[]; notice_days: number };
export type BranchSetting = { base: string; base_label: string; tax_rate: number | null; evcat_rate: number; evcat_cap: number | null;
  accessories: number | null; commission_rate: number | null; per_vehicle: boolean; note: string };
export type BranchSettings = { items: Record<string, BranchSetting>; confirmed: boolean; bases: Record<string, string> };
export type ContractFilters = Partial<{ f: string; q: string; branch: string; owner: string; company_id: number; contact_id: number;
  policy: string; insurer: string; end_from: string; end_to: string; sort: string; limit: number }>;
export type ContractInput = Partial<{ client_name: string; company_id: number | null; contact_id: number | null; insurer_id: number | null;
  insurer_name: string; branch: string; policy_number: string; premium: string | number | null; rate: string | null;
  commission_rate: string | number | null; base_amount: string | number | null; accessories: string | number | null;
  tax_rate: string | number | null; evcat_rate: string | number | null; evcat_cap: string | number | null; start_date: string | null; end_date: string | null; notice_days: string | number | null;
  tacit: boolean; owner_id: number | null; notes: string }>;
export type ContractDraftItem = { branch: string; choices: { company_id: number; name: string; premium: number | null; rate: string | null; status: string }[];
  insurer_id: number | null; premium: number | null; rate: string | null; policy_number: string; commission_rate: number | null; base_amount?: number | null;
  start_date: string | null; end_date: string | null; notice_days: number };
export type ContractDraft = { items: ContractDraftItem[]; renewal_of: Contract | null };
export type QuoteDetail = QuoteSummary & {
  contracts: ContractLink[]; renewal_of: ContractLink | null;
  fields: Record<string, string>; notes: string; current_insurer: string | null; current_rate: string | null; closed_at: string | null;
  field_defs: BranchField[]; docs: string[]; missing_labels: string[]; all_branches: string[];
  company: { id: number; name: string } | null; contact: QuotePerson | null;
  companies: QuoteCompany[]; files: QuoteFileRow[]; reminders: QuoteReminder[]; events: QuoteEventRow[];
};
export type QuoteList = { items: QuoteSummary[]; stages: { key: QuoteStage; label: string }[]; branches: string[] };
export type QuoteDraft = { kind: "request" | "followup" | "renegotiate"; followup: boolean; company: string; company_id: number;
  insurer_ids: number[]; branches: string[]; to: string[]; options: QuotePerson[];
  subject: string; body: string; in_reply_to: string | null; missing: string[];
  attachments: { id: number; name: string; size: number; label: string; kind: QuoteFileKind; checked: boolean }[] };
export type SendAllReport = { company: string; ok: boolean; to?: string[]; reason?: string }[];
export type QuoteInput = Partial<{ branch: string; branches: string[]; client_name: string; company_id: number | null; contact_id: number | null;
  owner_id: number | null; due_on: string | null; current_insurer: string | null; current_premium: string | number | null; current_rate: string | null;
  notes: string; title: string; stage: QuoteStage; lost_reason: string; fields: Record<string, string | null>; insurer_ids: number[] }>;

/** V3 : un employé (compte de connexion). */
export type TeamUser = {
  id: number; email: string; full_name: string; role: "admin" | "user"; active: boolean; linked: boolean;
  last_seen_at: string | null; mailbox: string | null; contacts: number;
};
export type Adoption = {
  steps: { key: string; label: string; setup: boolean }[];
  items: {
    id: number; name: string; email: string; last_seen_at: string | null;
    level: "invited" | "idle" | "setup" | "testing" | "quiet" | "active"; level_label: string;
    steps: Record<string, boolean>; done: number; total: number; test_mode: boolean;
    activity: { sent_real_7d: number; sent_test_7d: number; replies_7d: number; to_classify: number; active_campaigns: number; open_quotes: number };
  }[];
};
export type Me = (TeamUser & { server_mode: true }) | { id: null; role: "admin"; server_mode: false };

export type ProspectOption = { value: string; label: string };
export type ProspectCriteria = { functions: string[]; sectors: string[]; details?: string[]; cities: string[]; sizes: string[]; wanted: number };
export type ProspectSearch = {
  id: number; status: "preview" | "running" | "done" | "stopped" | "failed"; criteria: ProspectCriteria; summary: string;
  wanted: number; total_found: number | null; checked: number; emails_found: number; imported: number;
  skipped_existing: number; skipped_no_email: number; skipped_excluded: number; cost_usd: number;
  list_id: number | null; error: string | null; created_at: string | null; finished_at: string | null;
  estimate?: { findable_ratio: number; reachable: number; pages: number; cost_usd: number };
  sample?: { first: string; last: string; title: string | null; company: string | null; industry: string | null; size: string | null; city: string | null; findable: boolean }[];
};
export type ProspectingIndex = {
  configured: boolean; items: ProspectSearch[];
  options: { functions: ProspectOption[]; sectors: (ProspectOption & { details: ProspectOption[] })[]; cities: string[]; sizes: ProspectOption[]; max_wanted: number; page_cost: number; email_cost: number };
};

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

/** Télécharge un fichier servi par l'API (avec la connexion de l'employé) sous le nom donné. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const token = await accessToken();
  const res = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new ApiError(`Erreur ${res.status}`, res.status);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
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
  followupsDismiss: (ids: number[]) => request<{ dismissed: number }>("/api/followups/dismiss", { method: "POST", json: { contact_ids: ids } }),
  followupsRestore: (ids: number[]) => request<{ ok: boolean }>("/api/followups/restore", { method: "POST", json: { contact_ids: ids } }),
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
  mailList: (folder: string, days: number, refresh = false, q?: string) => request<MailList>(`/api/mailbox/messages${qs({ folder, days, refresh: refresh || undefined, q: q || undefined })}`),
  mailForward: (folder: string, uid: number) => request<{ attachments: Attachment[]; skipped: string[] }>(`/api/mailbox/messages/${uid}/forward${qs({ folder })}`, { method: "POST" }),
  mailArchive: (folder: string, uid: number) => request<{ archive_folder: string; message_id: string }>(`/api/mailbox/messages/${uid}/archive${qs({ folder })}`, { method: "POST" }),
  mailUnarchive: (message_id: string, folder: string, kind: "archive" | "junk" = "archive") =>
    request<{ ok: boolean }>("/api/mailbox/unarchive", { method: "POST", json: { message_id, folder, kind } }),
  mailSpam: (folder: string, uid: number) => request<{ archive_folder: string; message_id: string }>(`/api/mailbox/messages/${uid}/spam${qs({ folder })}`, { method: "POST" }),
  campaignSent: (id: number) => request<CampaignSent>(`/api/campaigns/${id}/sent`),
  campaignUpcoming: (id: number, enrollmentId?: number) =>
    request<CampaignUpcoming>(`/api/campaigns/${id}/upcoming${enrollmentId ? `?enrollment_id=${enrollmentId}` : ""}`),
  mailPreview: (partUrl: string) => request<AttachmentPreview>(partUrl.replace("/part/", "/preview/")),
  mailMessage: (folder: string, uid: number) => request<MailMessage>(`/api/mailbox/messages/${uid}${qs({ folder })}`),
  mailUnread: () => request<{ unread: number | null }>("/api/mailbox/unread"),
  mailSeen: (folder: string, uid: number, seen = true) =>
    request<{ ok: boolean; seen: boolean }>(`/api/mailbox/messages/${uid}/seen${qs({ folder, seen })}`, { method: "POST" }),
  mailSuggest: (q: string) => request<{ items: AddressSuggestion[] }>(`/api/mailbox/suggest?q=${encodeURIComponent(q)}`),
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
    request<ImportDone>(`/api/import/${token}/commit`, { method: "POST", json: { sheet, mapping } }),
  // V3.6 : listes de contacts
  lists: () => request<{ items: ContactListItem[] }>("/api/lists"),
  listCreate: (name: string, contact_ids: number[] = []) => request<ContactListItem>("/api/lists", { method: "POST", json: { name, contact_ids } }),
  listRename: (id: number, name: string) => request<ContactListItem>(`/api/lists/${id}`, { method: "PUT", json: { name } }),
  listDelete: (id: number) => request<{ ok: boolean }>(`/api/lists/${id}`, { method: "DELETE" }),
  listAdd: (id: number, contact_ids: number[]) => request<ContactListItem & { added: number }>(`/api/lists/${id}/members`, { method: "POST", json: { contact_ids } }),
  listRemove: (id: number, contact_ids: number[]) => request<ContactListItem & { removed: number }>(`/api/lists/${id}/members/remove`, { method: "POST", json: { contact_ids } }),
  listShare: (id: number, shared: boolean) => request<ContactListItem>(`/api/lists/${id}/share`, { method: "POST", json: { shared } }),
  prospecting: () => request<ProspectingIndex>("/api/prospecting"),
  prospectingBalance: () => request<{ balance: number }>("/api/prospecting/balance"),
  prospectingSetKey: (key: string) => request<{ configured: boolean; balance: number }>("/api/prospecting/key", { method: "PUT", json: { key } }),
  prospectingDeleteKey: () => request<{ configured: boolean }>("/api/prospecting/key", { method: "DELETE" }),
  prospectingPreview: (c: ProspectCriteria) => request<ProspectSearch>("/api/prospecting/preview", { method: "POST", json: c }),
  prospectingGet: (id: number) => request<ProspectSearch>(`/api/prospecting/${id}`),
  prospectingStart: (id: number, wanted: number) => request<ProspectSearch>(`/api/prospecting/${id}/start`, { method: "POST", json: { wanted } }),
  prospectingStop: (id: number) => request<ProspectSearch>(`/api/prospecting/${id}/stop`, { method: "POST" }),
  campaignNoReplyList: (id: number) => request<ContactListItem>(`/api/campaigns/${id}/no-reply-list`, { method: "POST" }),
  importCancel: (token: string) => request(`/api/import/${token}`, { method: "DELETE" }),
  exclusions: () => request<Exclusion[]>("/api/exclusions"),
  exclusionAdd: (entry: string, note: string) =>
    request<{ entry: string; added: boolean; affected: number }>("/api/exclusions", { method: "POST", json: { entry, note } }),
  exclusionDelete: (id: number) => request(`/api/exclusions/${id}`, { method: "DELETE" }),

  sequences: () => request<SequenceList>("/api/sequences"),
  sequenceCreate: (name: string, category: SequenceCategory = "prospection", steps = 3) =>
    request<{ id: number }>("/api/sequences", { method: "POST", json: { name, category, steps } }),
  sequenceDuplicate: (id: number) => request<{ id: number }>(`/api/sequences/${id}/duplicate`, { method: "POST" }),
  sequenceShare: (id: number) => request<SequenceData>(`/api/sequences/${id}/share`, { method: "POST" }),
  sequenceUnshare: (id: number) => request<SequenceData>(`/api/sequences/${id}/unshare`, { method: "POST" }),
  campaignRename: (id: number, name: string) => request<{ name: string }>(`/api/campaigns/${id}/name`, { method: "PUT", json: { name } }),
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
  blockVariant: (id: number, number?: number) => request<Block>(`/api/blocks/${id}/variant`, { method: "POST", json: number ? { number } : {} }),
  campaignBlocks: (id: number, map: BlockMap) => request<{ block_map: BlockMap }>(`/api/campaigns/${id}/blocks`, { method: "PUT", json: map }),
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
  activation: (id: number, overlap: boolean, recent = false) => request<Activation>(`/api/campaigns/${id}/activation${qs({ overlap, recent })}`),
  activate: (id: number, overlap: boolean, recent = false) => request<{ enrolled: number }>(`/api/campaigns/${id}/activate`, { method: "POST", json: { overlap, recent } }),
  contactNewAddress: (id: number, email: string) => request<{ id: number }>(`/api/contacts/${id}/new-address`, { method: "POST", json: { email } }),
  campaignAction: (id: number, action: "pause" | "resume" | "delete") => request(`/api/campaigns/${id}/${action}`, { method: "POST" }),

  replies: (f: string) => request<Replies>(`/api/replies${qs({ f })}`),
  classify: (id: number, classification: string, callback_on?: string, note?: string) =>
    request<Reply>(`/api/replies/${id}/classify`, { method: "POST", json: { classification, callback_on, note } }),
  replyNote: (id: number, note: string) => request(`/api/replies/${id}/note`, { method: "PUT", json: { note } }),
  attach: (id: number, contactId: number) => request(`/api/replies/${id}/attach`, { method: "POST", json: { contact_id: contactId } }),
  dismiss: (id: number) => request(`/api/replies/${id}/dismiss`, { method: "POST" }),
  repliesSeen: (ids: number[] | null, seen = true) =>
    request<{ ok: boolean; count: number }>(`/api/replies/seen`, { method: "POST", json: { ids, seen } }),

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

  quotes: (f: { company_id?: number; contact_id?: number } = {}) => request<QuoteList>(`/api/quotes${qs(f)}`),
  quote: (id: number) => request<QuoteDetail>(`/api/quotes/${id}`),
  quoteBranches: () => request<{ items: BranchDef[] }>("/api/quotes/branches"),
  quotePeople: () => request<{ items: { id: number; name: string }[] }>("/api/quotes/people"),
  quoteInsurerCompanies: () => request<{ items: { id: number; name: string; logo: string | null; contacts: number }[] }>("/api/quotes/insurer-companies"),
  quoteCreate: (body: QuoteInput) => request<QuoteDetail>("/api/quotes", { method: "POST", json: body }),
  quoteUpdate: (id: number, body: QuoteInput) => request<QuoteDetail>(`/api/quotes/${id}`, { method: "PATCH", json: body }),
  // Contrats et échéances
  contracts: (p: ContractFilters = {}) => request<ContractList>(`/api/contracts${qs(p)}`),
  contractsExportUrl: (p: ContractFilters = {}) => `/api/contracts/export.xlsx${qs(p)}`,
  contractBranches: () => request<BranchSettings>("/api/contracts/branches"),
  contractBranchesSave: (items: Record<string, Partial<Record<keyof BranchSetting, string | number | boolean | null>>>) =>
    request<BranchSettings>("/api/contracts/branches", { method: "PUT", json: { items } }),
  contract: (id: number) => request<Contract>(`/api/contracts/${id}`),
  contractCreate: (body: ContractInput) => request<Contract>("/api/contracts", { method: "POST", json: body }),
  contractUpdate: (id: number, body: ContractInput) => request<Contract>(`/api/contracts/${id}`, { method: "PATCH", json: body }),
  contractDelete: (id: number) => request<{ ok: boolean }>(`/api/contracts/${id}`, { method: "DELETE" }),
  contractRenew: (id: number, body: ContractInput) => request<Contract>(`/api/contracts/${id}/renew`, { method: "POST", json: body }),
  contractStartRenewal: (id: number) => request<{ quote_id: number; contract: Contract }>(`/api/contracts/${id}/start-renewal`, { method: "POST" }),
  contractEnd: (id: number, reason: string) => request<Contract>(`/api/contracts/${id}/end`, { method: "POST", json: { reason } }),
  quoteContractDraft: (id: number) => request<ContractDraft>(`/api/quotes/${id}/contract-draft`),
  quoteWin: (id: number, items: Partial<ContractDraftItem>[]) =>
    request<{ contracts: Contract[]; quote: QuoteDetail }>(`/api/quotes/${id}/win`, { method: "POST", json: { items } }),
  quoteDelete: (id: number) => request(`/api/quotes/${id}`, { method: "DELETE" }),
  quoteNote: (id: number, text: string) => request<QuoteDetail>(`/api/quotes/${id}/notes`, { method: "POST", json: { text } }),
  quoteAddInsurers: (id: number, company_ids: number[], branches?: string[]) =>
    request<QuoteDetail>(`/api/quotes/${id}/insurers`, { method: "POST", json: { company_ids, branches } }),
  quoteInsurerUpdate: (id: number, iid: number, body: Partial<{ status: InsurerStatus; recipients: string[]; offer_premium: string | number | null; offer_rate: string | null; notes: string }>) =>
    request<QuoteDetail>(`/api/quotes/${id}/insurers/${iid}`, { method: "PATCH", json: body }),
  quoteInsurerRemove: (id: number, iid: number) => request<QuoteDetail>(`/api/quotes/${id}/insurers/${iid}`, { method: "DELETE" }),
  quoteDraft: (id: number, body: { insurer_ids: number[]; to?: string[] }) => request<QuoteDraft>(`/api/quotes/${id}/draft`, { method: "POST", json: body }),
  quoteSend: (id: number, body: { insurer_ids: number[]; to: string[]; cc?: string; subject: string; body: string; attachment_ids: number[]; force?: boolean }) =>
    request<QuoteDetail>(`/api/quotes/${id}/send`, { method: "POST", json: body }),
  quotePreview: (id: number, body: { to: string[]; cc?: string; subject: string; body: string; attachment_names?: string[] }) =>
    request<QuotePreview>(`/api/quotes/${id}/preview`, { method: "POST", json: body }),
  quoteCompanyEmails: (id: number, companyId: number) => request<QuoteCompanyEmails>(`/api/quotes/${id}/companies/${companyId}/emails`),
  quoteFollowups: (id: number, companyId: number, enabled: boolean) =>
    request<QuoteDetail>(`/api/quotes/${id}/companies/${companyId}/followups`, { method: "POST", json: { enabled } }),
  quoteSendAll: (id: number, company_ids?: number[]) =>
    request<{ report: SendAllReport; quote: QuoteDetail }>(`/api/quotes/${id}/send-all`, { method: "POST", json: { company_ids } }),
  quoteReminder: (id: number, body: { title: string; due_on: string; due_time?: string | null; kind?: ReminderKind; notes?: string }) =>
    request<QuoteDetail>(`/api/quotes/${id}/reminders`, { method: "POST", json: body }),
  quoteAddFile: (id: number, body: { attachment_id: number; kind: QuoteFileKind; label?: string; insurer_id?: number | null }) =>
    request<QuoteDetail>(`/api/quotes/${id}/files`, { method: "POST", json: body }),
  quoteFileFromMail: (id: number, body: { folder: string; uid: number; index: number; kind: QuoteFileKind; insurer_id?: number | null }) =>
    request<QuoteDetail>(`/api/quotes/${id}/files/from-mail`, { method: "POST", json: body }),
  quoteRemoveFile: (id: number, fid: number) => request<QuoteDetail>(`/api/quotes/${id}/files/${fid}`, { method: "DELETE" }),

  me: () => request<Me>("/api/me"),
  team: () => request<TeamUser[]>("/api/admin/users"),
  teamAdoption: () => request<Adoption>("/api/admin/adoption"),
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
