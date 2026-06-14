import type {
  CatalogFilters,
  CatalogListResponse,
  CatalogStats,
  CharacterCollectResult,
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
    return response.json() as Promise<{ created: number; updated: number }>;
  },
};
