import type {
  CandidateResponse,
  CandidateSource,
  CreateVacancyRequest,
  SearchRequest,
  SearchResponse,
  VacancyResponse,
} from "./types";

/**
 * Тонкий API-клиент. Все запросы идут через /api/v1 (проксируется Next rewrites
 * на бэкенд, см. next.config.mjs). В dev — ATS_STUB_MODE=1 на бэкенде.
 */

const BASE = "/api/v1";

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // тело не JSON
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// --- Вакансии ---

export const api = {
  createVacancy: (data: CreateVacancyRequest) =>
    request<VacancyResponse>("/vacancies", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // --- Кандидаты ---

  uploadResume: async (
    file: File,
    source: CandidateSource = "direct",
  ): Promise<CandidateResponse> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(
      `${BASE}/candidates/upload-resume?source=${source}`,
      {
        method: "POST",
        body: form,
      },
    );
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        // ignore
      }
      throw new ApiError(res.status, detail);
    }
    return res.json();
  },

  // --- Поиск ---

  searchCandidates: (data: SearchRequest) =>
    request<SearchResponse>("/search/candidates", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};
