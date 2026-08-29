/**
 * Типы API-контрактов ATS Core.
 * Зеркалируют Pydantic-схемы бэкенда.
 */

// --- Вакансии ---

export type Seniority =
  | "intern"
  | "junior"
  | "middle"
  | "senior"
  | "lead"
  | "head";

export const SENIORITY_LABELS: Record<Seniority, string> = {
  intern: "Стажёр",
  junior: "Junior",
  middle: "Middle",
  senior: "Senior",
  lead: "Lead",
  head: "Head",
};

export interface CreateVacancyRequest {
  title: string;
  seniority: Seniority;
  team: string;
  description: string;
  requirements?: string[];
  nice_to_have?: string[];
}

export interface VacancyResponse {
  id: string;
  title: string;
  seniority: Seniority;
  team: string;
  status: string;
  criteria_provenance_id: string | null;
  criteria: ScreeningCriteriaOutput | null;
  criteria_error: string | null;
}

// --- AI-критерии скрининга (whitebox) ---

export type CriterionCategory =
  | "hard_skill"
  | "soft_skill"
  | "experience"
  | "education"
  | "red_flag";

export const CATEGORY_LABELS: Record<CriterionCategory, string> = {
  hard_skill: "Hard skills",
  soft_skill: "Soft skills",
  experience: "Опыт",
  education: "Образование",
  red_flag: "Red flags",
};

export interface Criterion {
  name: string;
  description: string;
  category: CriterionCategory;
  weight: number;
  verification: string;
  must_have: boolean;
}

export interface CriterionGroup {
  category: CriterionCategory;
  weight: number;
  criteria: Criterion[];
}

export interface ScreeningCriteriaOutput {
  summary: string;
  groups: CriterionGroup[];
  scoring_logic: string;
  reasoning: string;
}

// --- Кандидаты ---

export type CandidateSource =
  | "referral"
  | "job_board"
  | "database"
  | "agency"
  | "direct"
  | "linkedin"
  | "other";

export const CANDIDATE_SOURCE_LABELS: Record<CandidateSource, string> = {
  referral: "Реферал",
  job_board: "Джобборд",
  database: "База",
  agency: "Агентство",
  direct: "Прямой отклик",
  linkedin: "LinkedIn",
  other: "Другое",
};

export interface CandidateResponse {
  id: string;
  full_name: string;
  headline: string;
  skills: string[];
  source: CandidateSource;
  resume_provenance: string | null;
}

// --- Поиск ---

export type FilterOperator = "any" | "all" | "gte" | "lte";

export interface SearchFilter {
  field: string;
  values: string[];
  operator: FilterOperator;
}

export interface SearchRequest {
  query: string;
  filters?: SearchFilter[];
  limit?: number;
  offset?: number;
  facet_fields?: string[];
  bm25_weight?: number;
  vector_weight?: number;
  skip_embedding?: boolean;
}

export interface SearchHit {
  document_id: string;
  score: number;
  bm25_score: number;
  vector_score: number;
  headline: string;
  skills: string[];
  snippet: string;
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface Facet {
  field: string;
  values: FacetValue[];
}

export interface SearchResponse {
  hits: SearchHit[];
  total: number;
  facets: Facet[];
  took_ms: number;
  query: string;
}
