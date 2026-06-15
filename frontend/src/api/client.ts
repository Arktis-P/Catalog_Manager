import type {
  AppSettings,
  AppearanceReviewListResponse,
  CatalogFilters,
  CatalogListResponse,
  CatalogStats,
  CharacterCollectResult,
  CharacterListResponse,
  CollectJob,
  DanbooruStatus,
  GenerationCandidateListResponse,
  GenerationQueuePreview,
  GenerationStartPayload,
  NaiaStatus,
  Series,
  SeriesCreatePayload,
  SeriesListResponse,
  SeriesMergeCandidate,
  SeriesMergePreview,
  SeriesMergeResult,
  SeriesUpdatePayload,
} from "../types";

const API_BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      searchParams.set(key, String(value));
    }
  }
  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  getCatalogStats: () => request<CatalogStats>("/catalog/stats"),

  listCatalog: (filters: CatalogFilters = {}) =>
    request<CatalogListResponse>(`/catalog${buildQuery(filters as Record<string, string | number | boolean | undefined>)}`),

  getCatalogStatuses: () => request<string[]>("/catalog/statuses"),

  listSeries: (params: {
    status?: string;
    search?: string;
    sort_by?: string;
    sort_order?: string;
    limit?: number;
    hierarchical?: boolean;
  } = {}) => request<SeriesListResponse>(`/series${buildQuery(params)}`),

  listSeriesMergeCandidates: (
    seriesId: number,
    params: { mode?: "parent" | "child"; search?: string } = {},
  ) =>
    request<{ items: SeriesMergeCandidate[] }>(
      `/series/${seriesId}/merge/candidates${buildQuery(params)}`,
    ),

  previewSeriesMerge: (childSeriesId: number, parentSeriesId: number) =>
    request<SeriesMergePreview>(
      `/series/${childSeriesId}/merge/preview${buildQuery({ parent_series_id: parentSeriesId })}`,
    ),

  mergeSeries: (childSeriesId: number, parentSeriesId: number) =>
    request<SeriesMergeResult>(`/series/${childSeriesId}/merge`, {
      method: "POST",
      body: JSON.stringify({ parent_series_id: parentSeriesId }),
    }),

  unmergeSeries: (childSeriesId: number) =>
    request<{ child_series_id: number; child_series_tag: string; moved_back_count: number; child_character_count: number }>(
      `/series/${childSeriesId}/merge`,
      { method: "DELETE" },
    ),

  getSeriesStatuses: () => request<string[]>("/series/statuses"),

  createSeries: (payload: SeriesCreatePayload) =>
    request<Series>("/series", { method: "POST", body: JSON.stringify(payload) }),

  updateSeries: (id: number, payload: SeriesUpdatePayload) =>
    request<Series>(`/series/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),

  deleteSeries: (id: number) => request<void>(`/series/${id}`, { method: "DELETE" }),

  collectCharactersForSeries: (seriesId: number) =>
    request<CharacterCollectResult>(`/characters/series/${seriesId}/collect`, { method: "POST" }),

  startCollectCharactersJob: (seriesId: number) =>
    request<CollectJob>(`/characters/series/${seriesId}/collect/start`, { method: "POST" }),

  startAppearanceExtractJob: (seriesId: number) =>
    request<CollectJob>(`/characters/series/${seriesId}/appearance/start`, { method: "POST" }),

  getCollectJob: (jobId: string) => request<CollectJob>(`/characters/collect/jobs/${jobId}`),

  listCollectJobs: () => request<{ items: CollectJob[] }>("/characters/collect/jobs"),

  getSettings: () => request<AppSettings>("/settings"),

  updateSettings: (
    payload: Partial<
      Pick<
        AppSettings,
        | "danbooru_collect_max_concurrent"
        | "naia_base_url"
        | "naia_portable_dir"
        | "generation_images_per_character"
        | "generation_prompt_prefix"
        | "generation_prompt_suffix"
        | "generation_negative_prompt"
      >
    >,
  ) => request<AppSettings>("/settings", { method: "PATCH", body: JSON.stringify(payload) }),

  listAppearanceReviews: (params: { series_tag?: string; search?: string; skip?: number; limit?: number } = {}) =>
    request<AppearanceReviewListResponse>(`/review/appearance${buildQuery(params)}`),

  confirmAppearanceReview: (characterId: number) =>
    request<{ id: number; appearance_confirmed: boolean; generation_prompt: string | null }>(
      `/review/appearance/${characterId}/confirm`,
      { method: "POST" },
    ),

  getDanbooruStatus: () => request<DanbooruStatus>("/characters/danbooru/status"),

  updateCharacterSeries: (characterId: number, seriesId: number) =>
    request<{ id: number; series_id: number; series_tag: string; character_tag: string; post_count: number }>(
      `/characters/${characterId}/series`,
      { method: "PATCH", body: JSON.stringify({ series_id: seriesId }) },
    ),

  collectCharactersBatch: (payload: { status?: string; limit?: number }) =>
    request<{ series_processed: number; total_created: number; total_discovered: number; total_skipped_existing: number }>(
      "/characters/collect",
      { method: "POST", body: JSON.stringify(payload) },
    ),

  listSeriesCharacters: (
    seriesId: number,
    params: { search?: string; skip?: number; limit?: number } = {},
  ) => request<CharacterListResponse>(`/characters/series/${seriesId}/characters${buildQuery(params)}`),

  exportCharactersCsv: async (params: { series_id?: number; search?: string } = {}) => {
    const response = await fetch(`${API_BASE}/characters/export/csv${buildQuery(params)}`);
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "Character CSV export failed");
    }
    return response.text();
  },

  exportSeriesCsv: async () => {
    const response = await fetch(`${API_BASE}/series/export/csv`);
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "Series CSV export failed");
    }
    return response.text();
  },

  importSeriesCsv: async (file: File, replace = false) => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_BASE}/series/import/csv${replace ? "?replace=true" : ""}`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "CSV import failed");
    }
    return response.json() as Promise<{ created: number; updated: number; merged_duplicates?: number }>;
  },

  getNaiaStatus: () => request<NaiaStatus>("/generation/naia/status"),

  listGenerationCandidates: (
    seriesId: number,
    params: { require_confirmed?: boolean; search?: string } = {},
  ) =>
    request<GenerationCandidateListResponse>(
      `/generation/series/${seriesId}/candidates${buildQuery(params)}`,
    ),

  previewGenerationQueue: (seriesId: number, payload: GenerationStartPayload) =>
    request<GenerationQueuePreview>(`/generation/series/${seriesId}/preview-queue`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  startGenerationJob: (seriesId: number, payload: GenerationStartPayload) =>
    request<CollectJob>(`/generation/series/${seriesId}/start`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getGenerationJob: (jobId: string) => request<CollectJob>(`/generation/jobs/${jobId}`),

  listGenerationJobs: () => request<{ items: CollectJob[] }>("/generation/jobs"),

  cancelGenerationJob: (jobId: string) =>
    request<CollectJob>(`/generation/jobs/${jobId}/cancel`, { method: "POST" }),
};
