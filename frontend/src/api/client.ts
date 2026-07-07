import type {
  AppSettings,
  AppearanceReviewListResponse,
  AppearanceReviewItem,
  CatalogFilters,
  CatalogItem,
  CatalogItemUpdatePayload,
  CatalogListResponse,
  CatalogReviewCompletePayload,
  CatalogReviewFilterStatus,
  CatalogReviewListResponse,
  CatalogStats,
  GlobalCatalogReviewListResponse,
  CatalogJob,
  CharacterCollectResult,
  CharacterLinkCandidate,
  CharacterLinkResult,
  CharacterListResponse,
  CollectJob,
  DanbooruStatus,
  GlobalCharacterListResponse,
  GenerationCandidateListResponse,
  GenerationQueuePreview,
  GenerationStartPayload,
  GlobalGenerationCandidateListResponse,
  GlobalGenerationStartPayload,
  NaiaStatus,
  NotificationDisplay,
  NotificationMode,
  PipelineStatus,
  ReviewRegenerateJob,
  ReviewRegenerateJobListResponse,
  Series,
  SeriesCreatePayload,
  SeriesListResponse,
  SeriesMergeCandidate,
  SeriesMergePreview,
  SeriesMergeResult,
  SeriesUpdatePayload,
  SuggestLevelResponse,
} from "../types";

const API_BASE = "/api";

const NETWORK_ERROR_HINT =
  "백엔드 API에 연결하지 못했습니다. scripts\\launch_desktop.bat 으로 앱을 실행했는지, " +
  "주소가 http://127.0.0.1:8000 인지 확인하세요. (개발 모드 5173 은 Vite 서버도 필요합니다)";

function isNetworkError(err: unknown): boolean {
  if (!(err instanceof TypeError)) {
    return false;
  }
  const message = err.message.toLowerCase();
  return message.includes("failed to fetch") || message.includes("networkerror");
}

function formatRequestError(err: unknown): string {
  if (isNetworkError(err)) {
    return NETWORK_ERROR_HINT;
  }
  return err instanceof Error ? err.message : "Request failed";
}

export async function waitForBackend(
  options: { attempts?: number; intervalMs?: number } = {},
): Promise<void> {
  const attempts = options.attempts ?? 40;
  const intervalMs = options.intervalMs ?? 500;
  let lastError: unknown = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(`${API_BASE}/health`, {
        headers: { "Content-Type": "application/json" },
      });
      if (response.ok) {
        return;
      }
      lastError = new Error(`Health check failed: ${response.status}`);
    } catch (err) {
      lastError = err;
      if (attempt < attempts - 1) {
        await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
      }
    }
  }
  throw new Error(formatRequestError(lastError));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      ...init,
    });
  } catch (err) {
    throw new Error(formatRequestError(err));
  }

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

  getRandomCatalogCharacter: (filters: Omit<CatalogFilters, "skip" | "limit"> = {}) =>
    request<CatalogItem>(`/catalog/random${buildQuery(filters as Record<string, string | number | boolean | undefined>)}`),

  updateCatalogItem: (characterId: number, payload: CatalogItemUpdatePayload) =>
    request<CatalogItem>(`/catalog/${characterId}`, { method: "PATCH", body: JSON.stringify(payload) }),

  exportCatalogCsv: async (filters: Omit<CatalogFilters, "skip" | "limit"> = {}) => {
    const response = await fetch(
      `${API_BASE}/catalog/export/csv${buildQuery(filters as Record<string, string | number | boolean | undefined>)}`,
    );
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "Catalog CSV export failed");
    }
    return {
      content: await response.text(),
      savedPath: response.headers.get("X-Export-Path"),
    };
  },

  getCatalogStatuses: () => request<string[]>("/catalog/statuses"),

  listSeries: (params: {
    status?: string;
    search?: string;
    sort_by?: string;
    sort_order?: string;
    skip?: number;
    limit?: number;
    hierarchical?: boolean;
  } = {}) => request<SeriesListResponse>(`/series${buildQuery(params)}`),

  listSeriesMergeCandidates: (
    seriesId: number,
    params: { mode?: "parent" | "child"; search?: string; exclude_ids?: number[]; source_ids?: number[]; limit?: number } = {},
  ) => {
    const { exclude_ids, source_ids, ...rest } = params;
    const query = {
      ...rest,
      ...(exclude_ids?.length ? { exclude_ids: exclude_ids.join(",") } : {}),
      ...(source_ids?.length ? { source_ids: source_ids.join(",") } : {}),
    };
    return request<{ items: SeriesMergeCandidate[] }>(
      `/series/${seriesId}/merge/candidates${buildQuery(query)}`,
    );
  },

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

  getSeries: (id: number) => request<Series>(`/series/${id}`),

  updateSeries: (id: number, payload: SeriesUpdatePayload) =>
    request<Series>(`/series/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),

  deleteSeries: (id: number) => request<void>(`/series/${id}`, { method: "DELETE" }),

  collectCharactersForSeries: (seriesId: number) =>
    request<CharacterCollectResult>(`/characters/series/${seriesId}/collect`, { method: "POST" }),

  startCollectCharactersJob: (seriesId: number) =>
    request<CollectJob>(`/characters/series/${seriesId}/collect/start`, { method: "POST" }),

  startCollectCharactersJobs: (seriesIds: number[]) =>
    request<{ items: CollectJob[] }>("/characters/collect/start-batch", {
      method: "POST",
      body: JSON.stringify({ series_ids: seriesIds }),
    }),

  startAppearanceExtractJob: (seriesId: number) =>
    request<CollectJob>(`/characters/series/${seriesId}/appearance/start`, { method: "POST" }),

  getCollectJob: (jobId: string) => request<CollectJob>(`/characters/collect/jobs/${jobId}`),

  cancelCollectJob: (jobId: string) =>
    request<CollectJob>(`/characters/collect/jobs/${jobId}/cancel`, { method: "POST" }),

  pauseCollectJob: (jobId: string) =>
    request<CollectJob>(`/characters/collect/jobs/${jobId}/pause`, { method: "POST" }),

  resumeCollectJob: (jobId: string) =>
    request<CollectJob>(`/characters/collect/jobs/${jobId}/resume`, { method: "POST" }),

  listCollectJobs: () => request<{ items: CollectJob[] }>("/characters/collect/jobs"),

  listGlobalCharacters: (params: {
    search?: string;
    gender?: string;
    collect_status?: string;
    series_id?: number;
    min_post_count?: number;
    max_post_count?: number;
    has_image?: boolean;
    has_cover?: boolean;
    is_alternative?: boolean;
    sort_by?: string;
    sort_order?: string;
    skip?: number;
    limit?: number;
  } = {}) => request<GlobalCharacterListResponse>(`/character-catalog/characters${buildQuery(params)}`),

  listCharacterLinkCandidates: (
    characterId: number,
    params: { mode?: "parent" | "child"; search?: string; exclude_ids?: number[]; limit?: number } = {},
  ) => {
    const { exclude_ids, ...rest } = params;
    const query = {
      ...rest,
      ...(exclude_ids?.length ? { exclude_ids: exclude_ids.join(",") } : {}),
    };
    return request<{ items: CharacterLinkCandidate[] }>(
      `/character-catalog/characters/${characterId}/link/candidates${buildQuery(query)}`,
    );
  },

  linkParentCharacter: (childId: number, parentCharacterId: number) =>
    request<CharacterLinkResult>(`/character-catalog/characters/${childId}/link`, {
      method: "POST",
      body: JSON.stringify({ parent_character_id: parentCharacterId }),
    }),

  unlinkParentCharacter: (childId: number) =>
    request<CharacterLinkResult>(`/character-catalog/characters/${childId}/link`, { method: "DELETE" }),

  startCatalogListJob: (minPostCount: number, restart = false) =>
    request<CatalogJob>("/character-catalog/list/start", {
      method: "POST",
      body: JSON.stringify({ min_post_count: minPostCount, restart }),
    }),

  startCatalogTagsJob: (characterIds: number[]) =>
    request<CatalogJob>("/character-catalog/tags/start", {
      method: "POST",
      body: JSON.stringify({ character_ids: characterIds }),
    }),

  retryFailedCatalogTags: (limit = 500) =>
    request<CatalogJob>("/character-catalog/tags/retry-failed", {
      method: "POST",
      body: JSON.stringify({ limit }),
    }),

  collectAllUncollectedCatalogTags: (limit?: number, chunkSize = 5000) =>
    request<{ items: CatalogJob[] }>("/character-catalog/tags/collect-all", {
      method: "POST",
      body: JSON.stringify({ limit: limit ?? null, chunk_size: chunkSize }),
    }),

  listCatalogJobs: () => request<{ items: CatalogJob[] }>("/character-catalog/jobs"),

  getCatalogJob: (jobId: string) => request<CatalogJob>(`/character-catalog/jobs/${jobId}`),

  cancelCatalogJob: (jobId: string) =>
    request<CatalogJob>(`/character-catalog/jobs/${jobId}/cancel`, { method: "POST" }),

  pauseCatalogJob: (jobId: string) =>
    request<CatalogJob>(`/character-catalog/jobs/${jobId}/pause`, { method: "POST" }),

  resumeCatalogJob: (jobId: string) =>
    request<CatalogJob>(`/character-catalog/jobs/${jobId}/resume`, { method: "POST" }),

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
        | "review_thumbnail_size"
        | "review_max_loaded_images"
        | "min_character_post_count"
        | "hf_token"
        | "hf_wd_model"
        | "notification_mode"
      >
    > & { notification_mode?: NotificationMode; notification_display?: NotificationDisplay },
  ) => request<AppSettings>("/settings", { method: "PATCH", body: JSON.stringify(payload) }),

  listAppearanceReviews: (params: { series_tag?: string; search?: string; skip?: number; limit?: number } = {}) =>
    request<AppearanceReviewListResponse>(`/review/appearance${buildQuery(params)}`),

  confirmAppearanceReview: (characterId: number) =>
    request<{ id: number; appearance_confirmed: boolean; generation_prompt: string | null }>(
      `/review/appearance/${characterId}/confirm`,
      { method: "POST" },
    ),

  updateAppearanceReview: (
    characterId: number,
    payload: Partial<{
      multi_color_hair: string | null;
      hair_color: string | null;
      hair_shape: string | null;
      eye_color: string | null;
      feature_tags: string | null;
      gender: string | null;
    }>,
  ) => request<AppearanceReviewItem>(`/review/appearance/${characterId}`, { method: "PATCH", body: JSON.stringify(payload) }),

  listCatalogReviews: (params: {
    series_id: number;
    filter_status?: CatalogReviewFilterStatus;
    search?: string;
    skip?: number;
    limit?: number;
  }) => request<CatalogReviewListResponse>(`/review/catalog${buildQuery(params)}`),

  suggestPromptLevel: (seriesId: number, characterIds?: number[]) =>
    request<SuggestLevelResponse>(
      `/generation/series/${seriesId}/suggest-level${
        characterIds && characterIds.length > 0
          ? `?character_ids=${characterIds.join(",")}`
          : ""
      }`,
    ),

  completeCatalogReview: (characterId: number, payload: CatalogReviewCompletePayload) =>
    request<{
      id: number;
      review_status: string;
      cover_image_id: number | null;
      gender: string | null;
      rating: number | null;
      final_prompt: string | null;
    }>(`/review/catalog/${characterId}/complete`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  undoCatalogReview: (characterId: number) =>
    request<{ id: number; review_status: string; cover_image_id: number | null }>(
      `/review/catalog/${characterId}/undo`,
      { method: "POST" },
    ),

  regenerateCatalogCharacter: (
    characterId: number,
    payload: { prompt: string; gender?: string | null },
  ) =>
    request<ReviewRegenerateJob>(`/review/catalog/${characterId}/regenerate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listReviewRegenerateJobs: () =>
    request<ReviewRegenerateJobListResponse>("/review/catalog/regenerate/jobs"),

  getReviewRegenerateJob: (jobId: string) =>
    request<ReviewRegenerateJob>(`/review/catalog/regenerate/jobs/${jobId}`),

  listCatalogReviewsGlobal: (
    params: { filter_status?: CatalogReviewFilterStatus; search?: string; skip?: number; limit?: number } = {},
  ) => request<GlobalCatalogReviewListResponse>(`/review/catalog-global${buildQuery(params)}`),

  completeCatalogReviewGlobal: (globalCharacterId: number, payload: CatalogReviewCompletePayload) =>
    request<{
      id: number;
      review_status: string;
      cover_image_id: number | null;
      gender: string | null;
      rating: number | null;
      final_prompt: string | null;
    }>(`/review/catalog-global/${globalCharacterId}/complete`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  undoCatalogReviewGlobal: (globalCharacterId: number) =>
    request<{ id: number; review_status: string; cover_image_id: number | null }>(
      `/review/catalog-global/${globalCharacterId}/undo`,
      { method: "POST" },
    ),

  dismissCatalogNeedsCheck: (characterId: number) =>
    request<{ id: number; character_status: string; needs_check_reason: string | null }>(
      `/review/catalog/${characterId}/dismiss-needs-check`,
      { method: "POST" },
    ),

  deleteCharacter: (characterId: number) =>
    request<{ id: number; character_tag: string; deleted: boolean }>(`/characters/${characterId}`, { method: "DELETE" }),

  getDanbooruStatus: () => request<DanbooruStatus>("/characters/danbooru/status"),

  startPipeline: (autoGenerate = false) =>
    request<PipelineStatus>(
      `/characters/pipeline/start?auto_generate=${autoGenerate}`,
      { method: "POST" },
    ),
  getPipelineStatus: () => request<PipelineStatus>("/characters/pipeline/status"),
  stopPipeline: () => request<PipelineStatus>("/characters/pipeline/stop", { method: "POST" }),

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
    params: { search?: string; status?: string; skip?: number; limit?: number } = {},
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
    params: {
      require_confirmed?: boolean;
      exclude_needs_check?: boolean;
      needs_check_only?: boolean;
      search?: string;
    } = {},
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

  listGlobalGenerationCandidates: (params: { search?: string; limit?: number } = {}) =>
    request<GlobalGenerationCandidateListResponse>(`/generation/characters/candidates${buildQuery(params)}`),

  startCharacterGenerationJob: (payload: GlobalGenerationStartPayload) =>
    request<CollectJob>("/generation/characters/start", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getGenerationJob: (jobId: string) => request<CollectJob>(`/generation/jobs/${jobId}`),

  listGenerationJobs: () => request<{ items: CollectJob[] }>("/generation/jobs"),

  cancelGenerationJob: (jobId: string) =>
    request<CollectJob>(`/generation/jobs/${jobId}/cancel`, { method: "POST" }),

  pauseGenerationJob: (jobId: string) =>
    request<CollectJob>(`/generation/jobs/${jobId}/pause`, { method: "POST" }),

  resumeGenerationJob: (jobId: string) =>
    request<CollectJob>(`/generation/jobs/${jobId}/resume`, { method: "POST" }),
};
