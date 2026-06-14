import type {
  AppSettings,
  CatalogFilters,
  CatalogListResponse,
  CatalogStats,
  CharacterCollectResult,
  CollectJob,
  DanbooruStatus,
  Series,
  SeriesCreatePayload,
  SeriesListResponse,
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
  } = {}) => request<SeriesListResponse>(`/series${buildQuery(params)}`),

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

  updateSettings: (payload: Pick<AppSettings, "danbooru_collect_max_concurrent">) =>
    request<AppSettings>("/settings", { method: "PATCH", body: JSON.stringify(payload) }),

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

  exportSeriesCsv: async () => {
    const response = await fetch(`${API_BASE}/series/export/csv`);
    if (!response.ok) {
      throw new Error("CSV export failed");
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
};
