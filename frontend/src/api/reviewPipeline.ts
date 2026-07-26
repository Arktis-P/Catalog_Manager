// Typed API client for the review pipeline endpoints (parent-child batch review,
// non-human triage, Danbooru reference comparison). Kept fully self-contained
// (own request/query helpers, own types) so it does not depend on api/client.ts
// or types/index.ts, which carry pre-existing edits owned by other work.

const API_BASE = "/api";

function isNetworkError(err: unknown): boolean {
  if (!(err instanceof TypeError)) {
    return false;
  }
  const message = err.message.toLowerCase();
  return message.includes("failed to fetch") || message.includes("networkerror");
}

function formatRequestError(err: unknown): string {
  if (isNetworkError(err)) {
    return "백엔드 API에 연결하지 못했습니다.";
  }
  return err instanceof Error ? err.message : "Request failed";
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
    if (init?.signal?.aborted) {
      throw err;
    }
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

// ── Shared pipeline types ───────────────────────────────────────────────

export interface PipelineImage {
  id: number;
  image_path: string;
  is_cover: boolean;
  is_rejected: boolean;
  auto_status: string | null;
  quality_status: string | null;
  identity_status: string | null;
  cover_score: number | null;
}

// ── Parent-child batch review ───────────────────────────────────────────

export interface ParentChildCandidate {
  id: number;
  character_tag: string;
  display_name: string;
  post_count: number;
  review_status: string;
  rating: number | null;
  gender: string | null;
  generation_status: string;
  parent_character_id: number | null;
  parent_character_tag: string | null;
  child_count: number;
  multi_color_hair: string | null;
  hair_color: string | null;
  hair_shape: string | null;
  eye_color: string | null;
  feature_tags: string | null;
  primary_hair_color: string | null;
  reasons: string[];
  confidence: number;
  default_selected: boolean;
  already_linked: boolean;
  preview_image: PipelineImage | null;
}

export interface ParentChildGroup {
  group_id: string;
  parent: ParentChildCandidate;
  children: ParentChildCandidate[];
  candidate_count: number;
  selected_count: number;
  conflict_count: number;
  reasons: string[];
}

export interface ParentChildGroupListResponse {
  items: ParentChildGroup[];
  total: number;
}

export interface ListParentChildGroupsParams {
  series_id?: number;
  search?: string;
  confidence?: "all" | "medium" | "high";
  already_linked_only?: boolean;
  unreviewed_first?: boolean;
  skip?: number;
  limit?: number;
}

export interface ParentChildApplyPayload {
  selected_child_ids: number[];
  unlink_child_ids: number[];
  inherit_tags?: boolean;
  apply_parent_rating?: boolean;
  complete_children?: boolean;
  complete_parent?: boolean;
}

export interface ParentChildApplyConflict {
  child_id: number;
  field: string;
  parent_value: string | null;
  child_value: string | null;
}

export interface ParentChildApplyResult {
  parent_id: number;
  linked_child_ids: number[];
  unlinked_child_ids: number[];
  inherited_fields: Record<number, string[]>;
  conflicts: ParentChildApplyConflict[];
  completed_child_ids: number[];
  parent_completed: boolean;
}

export interface ParentChildDismissResult {
  group_id: string;
  candidate_id: number;
  dismissed: boolean;
}

export function listParentChildGroups(
  params: ListParentChildGroupsParams = {},
  signal?: AbortSignal,
): Promise<ParentChildGroupListResponse> {
  return request<ParentChildGroupListResponse>(
    `/review/v2/parent-child-groups${buildQuery(params as Record<string, string | number | boolean | undefined | null>)}`,
    { signal },
  );
}

export function getParentChildGroup(
  groupId: string | number,
  confidence: "all" | "medium" | "high" = "all",
  signal?: AbortSignal,
): Promise<ParentChildGroup> {
  return request<ParentChildGroup>(
    `/review/v2/parent-child-groups/${groupId}${buildQuery({ confidence })}`,
    { signal },
  );
}

export function applyParentChildGroup(
  groupId: string | number,
  payload: ParentChildApplyPayload,
): Promise<ParentChildApplyResult> {
  return request<ParentChildApplyResult>(`/review/v2/parent-child-groups/${groupId}/apply`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function dismissParentChildCandidate(
  groupId: string | number,
  candidateId: number,
  reason?: string,
): Promise<ParentChildDismissResult> {
  return request<ParentChildDismissResult>(`/review/v2/parent-child-groups/${groupId}/dismiss-candidate`, {
    method: "POST",
    body: JSON.stringify({ candidate_id: candidateId, reason: reason ?? null }),
  });
}

// ── Danbooru reference comparison ───────────────────────────────────────

export interface DanbooruReferenceImage {
  post_id: number;
  preview_url: string | null;
  sample_url: string | null;
  file_url: string | null;
  width: number | null;
  height: number | null;
  rating: string | null;
  post_url: string;
}

export interface DanbooruReferenceImageListResponse {
  character_id: number;
  character_tag: string;
  images: DanbooruReferenceImage[];
  source: string;
  error: string | null;
}

export function getDanbooruReferenceImages(
  characterId: number,
  limit = 3,
  signal?: AbortSignal,
): Promise<DanbooruReferenceImageListResponse> {
  return request<DanbooruReferenceImageListResponse>(
    `/review/v2/global-characters/${characterId}/danbooru-reference-images${buildQuery({ limit })}`,
    { signal },
  );
}

// ── Non-human triage ────────────────────────────────────────────────────

export interface NonHumanCandidate {
  id: number;
  character_tag: string;
  display_name: string;
  post_count: number;
  score: number;
  reasons: string[];
  classifier_version: string;
  review_status: string;
  current_rating: number | null;
  non_human_review_result: string | null;
  gender: string | null;
  generation_status: string;
  series_tags: string[];
  related_tags: string[];
  preview_image: PipelineImage | null;
}

export interface NonHumanCandidateListResponse {
  items: NonHumanCandidate[];
  total: number;
}

export interface ListNonHumanCandidatesParams {
  review_filter?: "unreviewed" | "reviewed" | "general_review" | "all";
  category?: string;
  series_id?: number;
  search?: string;
  include_completed?: boolean;
  skip?: number;
  limit?: number;
}

export type NonHumanDecisionResult = "non_human" | "generation_unavailable" | "human_female" | "general_review";

export interface NonHumanDecisionResponse {
  id: number;
  result: NonHumanDecisionResult;
  review_status: string;
  rating: number | null;
  non_human_review_result: string | null;
}

export interface NonHumanDecisionOptions {
  completeReview?: boolean;
  // Must only be set true after an explicit user confirmation when reclassifying
  // a character that already carries a non-human decision.
  overwriteExisting?: boolean;
  // Must only be set true after an explicit user confirmation when reclassifying
  // a character whose review is already completed.
  reopenCompleted?: boolean;
}

export function listNonHumanCandidates(
  params: ListNonHumanCandidatesParams = {},
  signal?: AbortSignal,
): Promise<NonHumanCandidateListResponse> {
  return request<NonHumanCandidateListResponse>(
    `/review/v2/non-human-candidates${buildQuery(params as Record<string, string | number | boolean | undefined | null>)}`,
    { signal },
  );
}

export function applyNonHumanDecision(
  characterId: number,
  result: NonHumanDecisionResult,
  options: NonHumanDecisionOptions = {},
): Promise<NonHumanDecisionResponse> {
  const { completeReview = true, overwriteExisting = false, reopenCompleted = false } = options;
  return request<NonHumanDecisionResponse>(`/review/v2/non-human-candidates/${characterId}/decision`, {
    method: "POST",
    body: JSON.stringify({
      result,
      complete_review: completeReview,
      overwrite_existing: overwriteExisting,
      reopen_completed: reopenCompleted,
    }),
  });
}
