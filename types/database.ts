// ─────────────────────────────────────────────────────────────────────────────
// DocMap Intelligence OS — Supabase Database Types
//
// Mirrors the SQL schema in sql/001_clinic_intelligence.sql.
// The Database type is passed to createClient<Database> for type-safe queries.
// ─────────────────────────────────────────────────────────────────────────────

export type PipelineStage =
  | "Identified"
  | "Researching"
  | "Contact found"
  | "Outreach drafted"
  | "Contacted"
  | "Replied"
  | "Meeting booked"
  | "Demo completed"
  | "Proposal sent"
  | "Won"
  | "Lost"
  | "Paused";

export type SourceType =
  | "website_page"
  | "manual_note"
  | "email_thread"
  | "meeting_note";

export type ResearchRunStatus =
  | "queued"
  | "fetching"
  | "extracting"
  | "needs_review"
  | "approved"
  | "failed";

export type ObservationCategory =
  | "patient_journey"
  | "pricing"
  | "service"
  | "contact_route"
  | "positioning";

export type ReviewStatus = "draft" | "approved" | "rejected";
export type DraftStatus = "draft" | "approved" | "sent_elsewhere" | "archived";
export type InteractionType =
  | "manual_note"
  | "email_thread"
  | "meeting_note"
  | "call"
  | "system_event";
export type TaskStatus = "open" | "done" | "cancelled";

// ── Row types (direct table shape) ───────────────────────────────────────────

export interface ClinicAccount {
  id: string;
  name: string;
  website_url: string;
  owner_user: string;
  pipeline_stage: PipelineStage;
  fit_score: number;
  sales_angle: string | null;
  next_action: string | null;
  next_action_due_at: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface ClinicSource {
  id: string;
  clinic_account_id: string;
  type: SourceType;
  url: string | null;
  title: string;
  captured_at: string;
  raw_text: string;
  content_hash: string;
  approved_for_use: boolean;
}

export interface ClinicResearchRun {
  id: string;
  clinic_account_id: string;
  status: ResearchRunStatus;
  submitted_url: string;
  allowed_domain: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  created_by_user: string;
  created_at: string;
}

export interface ClinicObservation {
  id: string;
  clinic_account_id: string;
  source_id: string | null;
  category: ObservationCategory;
  text: string;
  confidence: number;
  review_status: ReviewStatus;
}

export interface ClinicContact {
  id: string;
  clinic_account_id: string;
  name: string;
  role: string;
  email: string | null;
  phone: string | null;
  source_id: string | null;
  confidence: number;
  review_status: ReviewStatus;
}

export interface ClinicInteraction {
  id: string;
  clinic_account_id: string;
  type: InteractionType;
  body: string;
  occurred_at: string;
  created_by_user: string;
  source_id: string | null;
}

export interface OutreachDraft {
  id: string;
  clinic_account_id: string;
  subject: string;
  body: string;
  tone: string;
  status: DraftStatus;
  generated_from_run_id: string | null;
  approved_by_user: string | null;
  approved_at: string | null;
  created_at: string;
}

export interface PipelineStageHistory {
  id: string;
  clinic_account_id: string;
  from_stage: PipelineStage | null;
  to_stage: PipelineStage;
  changed_by_user: string;
  changed_at: string;
  reason: string | null;
}

export interface AccountTask {
  id: string;
  clinic_account_id: string;
  owner_user: string;
  title: string;
  status: TaskStatus;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface DoctifyProfile {
  id: string;
  clinic_name: string;
  doctify_url: string;
  website_url: string | null;
  location: string | null;
  specialty_tags: string[];
  specialist_count: number | null;
  review_count: number | null;
  raw_json: Record<string, unknown>;
  scraped_at: string;
  clinic_account_id: string | null;
}

export interface DocumentEmbedding {
  id: string;
  entity_type: string;
  entity_id: string;
  content: string;
  created_at: string;
}

// ── Supabase Database generic — passed to createClient<Database>() ────────────
// Supabase JS v2 requires Row / Insert / Update / Relationships per table,
// plus Views / Functions / Enums / CompositeTypes at the schema level.

type NoRelationships = { Relationships: [] };

export type Database = {
  public: {
    Tables: {
      clinic_accounts: {
        Row: ClinicAccount;
        Insert: Omit<ClinicAccount, "id" | "created_at" | "updated_at"> & { id?: string };
        Update: Partial<Omit<ClinicAccount, "id" | "created_at">>;
      } & NoRelationships;
      clinic_sources: {
        Row: ClinicSource;
        Insert: Omit<ClinicSource, "id"> & { id?: string };
        Update: Partial<Omit<ClinicSource, "id">>;
      } & NoRelationships;
      clinic_research_runs: {
        Row: ClinicResearchRun;
        Insert: Omit<ClinicResearchRun, "id" | "created_at"> & { id?: string };
        Update: Partial<Omit<ClinicResearchRun, "id" | "created_at">>;
      } & NoRelationships;
      clinic_observations: {
        Row: ClinicObservation;
        Insert: Omit<ClinicObservation, "id"> & { id?: string };
        Update: Partial<Omit<ClinicObservation, "id">>;
      } & NoRelationships;
      clinic_contacts: {
        Row: ClinicContact;
        Insert: Omit<ClinicContact, "id"> & { id?: string };
        Update: Partial<Omit<ClinicContact, "id">>;
      } & NoRelationships;
      clinic_interactions: {
        Row: ClinicInteraction;
        Insert: Omit<ClinicInteraction, "id"> & { id?: string };
        Update: Partial<Omit<ClinicInteraction, "id">>;
      } & NoRelationships;
      outreach_drafts: {
        Row: OutreachDraft;
        Insert: Omit<OutreachDraft, "id" | "created_at"> & { id?: string };
        Update: Partial<Omit<OutreachDraft, "id" | "created_at">>;
      } & NoRelationships;
      pipeline_stage_history: {
        Row: PipelineStageHistory;
        Insert: Omit<PipelineStageHistory, "id"> & { id?: string };
        Update: never;
      } & NoRelationships;
      account_tasks: {
        Row: AccountTask;
        Insert: Omit<AccountTask, "id" | "created_at"> & { id?: string };
        Update: Partial<Omit<AccountTask, "id" | "created_at">>;
      } & NoRelationships;
      doctify_profiles: {
        Row: DoctifyProfile;
        Insert: Omit<DoctifyProfile, "id" | "scraped_at"> & { id?: string };
        Update: Partial<Omit<DoctifyProfile, "id" | "scraped_at">>;
      } & NoRelationships;
      document_embeddings: {
        Row: DocumentEmbedding;
        Insert: Omit<DocumentEmbedding, "id" | "created_at"> & { id?: string; embedding?: number[] };
        Update: Partial<Omit<DocumentEmbedding, "id" | "created_at">>;
      } & NoRelationships;
      integrated_practitioner_with_phin: {
        Row: Record<string, unknown>;
        Insert: never;
        Update: never;
      } & NoRelationships;
    };
    Views: Record<string, never>;
    Functions: {
      match_documents: {
        Args: {
          query_embedding: number[];
          match_count?: number;
          filter_type?: string | null;
        };
        Returns: {
          id: string;
          entity_type: string;
          entity_id: string;
          content: string;
          similarity: number;
        }[];
      };
    };
    Enums: Record<string, never>;
    CompositeTypes: Record<string, never>;
  };
};
