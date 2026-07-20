export interface Series {
  id: number;
  series_tag: string;
  display_name: string;
  post_count: number;
  priority: number;
  status: string;
  note: string | null;
  parent_series_id: number | null;
  parent_series_tag: string | null;
  character_count: number;
  own_character_count: number;
  merged_moved_count: number;
  merged_duplicate_count: number;
  child_count: number;
  is_merged_child: boolean;
  last_collect_created: number;
  last_collect_skipped: number;
  last_appearance_updated: number;
  appearance_extracted_count: number;
  all_appearance_collected: boolean;
  generation_pipeline_done: boolean;
  created_at: string;
  updated_at: string;
}

export interface SeriesMergeCandidate {
  id: number;
  series_tag: string;
  display_name: string;
  status: string;
  post_count: number;
  character_count: number;
  similarity_score: number;
  mergeable: boolean;
}

export interface SeriesMergePreview {
  child_series_id: number;
  child_series_tag: string;
  parent_series_id: number;
  parent_series_tag: string;
  child_character_count: number;
  duplicate_count: number;
  moved_count: number;
}

export interface SeriesMergeResult {
  child_series_id: number;
  child_series_tag: string;
  parent_series_id: number;
  parent_series_tag: string;
  moved_count: number;
  duplicate_count: number;
  parent_character_count: number;
}

export interface SeriesListResponse {
  items: Series[];
  total: number;
}

export interface CatalogItem {
  id: number;
  series_id: number;
  series_tag: string;
  series_display_name: string;
  character_tag: string;
  display_name: string;
  post_count: number;
  danbooru_url: string | null;
  cover_image: string | null;
  gender: string | null;
  type: string | null;
  rating: number | null;
  multi_color_hair: string | null;
  hair_color: string | null;
  hair_shape: string | null;
  eye_color: string | null;
  feature_tags: string | null;
  generation_prompt: string | null;
  final_prompt: string | null;
  character_status: string;
  catalog_status: string;
  has_cover_image: boolean;
  needs_review: boolean;
  needs_regen: boolean;
  is_alternative: boolean;
  parent_character_tag: string | null;
  parent_display_name: string | null;
}

export interface CatalogListResponse {
  items: CatalogItem[];
  total: number;
}

export interface GlobalCatalogItem extends Omit<CatalogItem, "series_id"> {
  series_id: number | null;
}

export interface GlobalCatalogListResponse {
  items: GlobalCatalogItem[];
  total: number;
}

export interface CatalogStats {
  series_count: number;
  character_count: number;
  completed_count: number;
  cover_image_count: number;
}

export interface CharacterCollectResult {
  series_tag: string;
  discovered: number;
  created: number;
  skipped_existing: number;
}

export interface CharacterDetail {
  id: number;
  series_id: number;
  series_tag: string;
  series_display_name: string;
  character_tag: string;
  display_name: string;
  danbooru_url: string | null;
  post_count: number;
  multi_color_hair: string | null;
  hair_color: string | null;
  hair_shape: string | null;
  eye_color: string | null;
  feature_tags: string | null;
  gender: string | null;
  generation_prompt: string | null;
  appearance_confirmed: boolean;
  status: string;
  source_series_id: number | null;
  source_series_tag: string | null;
  from_wiki: boolean;
  from_list_page: boolean;
  from_posts: boolean;
  from_related: boolean;
  needs_check_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface CharacterListResponse {
  items: CharacterDetail[];
  total: number;
}

export interface CollectJob {
  job_id: string;
  series_id: number;
  series_tag: string;
  job_type: "character_collect" | "appearance_extract" | "image_generation";
  status: string;
  phase: string;
  message: string;
  current: number;
  total: number;
  discovered: number;
  created: number;
  skipped_existing: number;
  updated: number;
  completed?: number;
  failed?: number;
  auto_pass?: number;
  auto_warning?: number;
  auto_reject?: number;
  prompt_level?: number;
  current_character_tag?: string;
  last_image_path?: string | null;
  queue_id?: string;
  error?: string | null;
  started_at: string;
  finished_at?: string | null;
}

export interface CharacterSeriesLinkInfo {
  series_id: number | null;
  series_tag: string | null;
  copyright_tag: string;
  relevance_rank: number;
  is_primary: boolean;
  is_auto: boolean;
  is_user_edited: boolean;
}

export interface GlobalCharacter {
  id: number;
  character_tag: string;
  display_name: string;
  post_count: number;
  collect_status: string;
  appearance_status: string;
  gender_status: string;
  series_status: string;
  multi_color_hair: string | null;
  hair_color: string | null;
  hair_shape: string | null;
  eye_color: string | null;
  feature_tags: string | null;
  gender: string | null;
  error_message: string | null;
  retry_count: number;
  last_collected_at: string | null;
  primary_series_tag: string | null;
  related_series_count: number;
  series_links: CharacterSeriesLinkInfo[];
  image_count: number;
  has_cover_image: boolean;
  parent_character_id: number | null;
  parent_character_tag: string | null;
  parent_display_name: string | null;
  is_alternative: boolean;
  child_count: number;
  created_at: string;
  updated_at: string;
}

export interface GlobalCharacterListResponse {
  items: GlobalCharacter[];
  total: number;
}

export interface GlobalCharacterImage {
  id: number;
  image_path: string;
  is_cover: boolean;
  auto_status: string | null;
}

export interface GlobalCharacterImagesResponse {
  id: number;
  images: GlobalCharacterImage[];
}

export interface CharacterLinkCandidate {
  id: number;
  character_tag: string;
  display_name: string;
  post_count: number;
  similarity_score: number;
  match_reason: string | null;
  linkable: boolean;
  review_status: string | null;
  rating: number | null;
  image_count: number;
  cover_image_path: string | null;
}

export interface CharacterLinkResult {
  child_id: number;
  child_character_tag: string;
  parent_id: number;
  parent_character_tag: string;
}

export type RelevanceCollectTarget = "selected" | "uncollected" | "min_posts";

export interface RelevanceCollectError {
  character_id: number;
  character_tag: string;
  error: string;
}

export interface RelevanceCollectJob {
  job_id: string;
  status: string;
  phase: string;
  message: string;
  current: number;
  total: number;
  success_count: number;
  error_count: number;
  current_character_tag: string;
  errors: RelevanceCollectError[];
  started_at: string;
  finished_at: string | null;
}

export interface RelevanceCollectStartPayload {
  target: RelevanceCollectTarget;
  character_ids?: number[];
  min_post_count?: number;
}

export type V2GenerationTarget = "selected" | "page" | "not_generated" | "min_posts";

export interface V2GenerationStartPayload {
  target: V2GenerationTarget;
  character_ids?: number[];
  min_post_count?: number;
  rerun?: boolean;
}

export interface CatalogJob {
  job_id: string;
  job_type: "character_catalog_list" | "character_catalog_tags";
  status: string;
  phase: string;
  message: string;
  current: number;
  total: number;
  created: number;
  updated: number;
  success_count: number;
  partial_count: number;
  failed_count: number;
  current_character_tag: string;
  active_items: string[];
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface GenerationCandidate {
  id: number;
  character_tag: string;
  display_name: string;
  post_count: number;
  generation_prompt: string | null;
  appearance_confirmed: boolean;
  gender: string | null;
  status: string;
  needs_check_reason: string | null;
}

export interface GenerationCandidateListResponse {
  items: GenerationCandidate[];
  total: number;
  total_characters: number;
  with_prompt: number;
  confirmed_with_prompt: number;
  unconfirmed_with_prompt: number;
  needs_check_with_prompt: number;
}

export interface NaiaStatus {
  configured: boolean;
  ready: boolean;
  base_url: string;
  portable_dir: string;
  wildcards_dir: string;
  message: string;
  api_mode?: string | null;
  is_generating?: boolean | null;
}

export interface GenerationQueuePreview {
  queue_id: string;
  series_id: number;
  series_tag: string;
  prompt_level: number;
  character_count: number;
  wildcard_path: string;
  manifest_path: string;
  prompt_template: string;
  prompt_prefix: string;
  prompt_suffix: string;
  negative_prompt: string;
  skipped: Array<Record<string, unknown>>;
}

export interface GenerationStartPayload {
  character_ids?: number[] | null;
  prompt_level?: number;
  require_confirmed?: boolean;
}

export interface SuggestLevelResponse {
  suggested_level: number;
  breakdown: Record<number, number>;
}

export interface GlobalGenerationCandidate {
  id: number;
  character_tag: string;
  display_name: string;
  post_count: number;
  gender: string | null;
}

export interface GlobalGenerationCandidateListResponse {
  items: GlobalGenerationCandidate[];
  total: number;
  total_completed: number;
  already_generated: number;
  remaining: number;
}

export interface GlobalGenerationStartPayload {
  character_ids: number[];
  prompt_level?: number;
}

export type NotificationMode = "each" | "all_done" | "none";
export type NotificationDisplay = "toast" | "browser" | "both";

export interface AppSettings {
  danbooru_collect_max_concurrent: number;
  danbooru_request_delay: number;
  naia_base_url: string;
  naia_portable_dir: string;
  generation_images_per_character: number;
  generation_prompt_prefix: string;
  generation_prompt_suffix: string;
  generation_negative_prompt: string;
  review_thumbnail_size: number;
  review_max_loaded_images: number;
  min_character_post_count: number;
  hf_token: string;
  hf_wd_model: string;
  notification_mode: NotificationMode;
  notification_display: NotificationDisplay;
  v2_review_card_size: string;
  v2_review_card_width_px: number;
}

export interface AppearanceReviewItem {
  id: number;
  series_tag: string;
  series_display_name: string;
  character_tag: string;
  display_name: string;
  post_count: number;
  danbooru_url: string | null;
  multi_color_hair: string | null;
  hair_color: string | null;
  hair_shape: string | null;
  eye_color: string | null;
  feature_tags: string | null;
  gender: string | null;
  generation_prompt: string | null;
  appearance_confirmed: boolean;
}

export interface AppearanceReviewListResponse {
  items: AppearanceReviewItem[];
  total: number;
}

export interface CatalogReviewImage {
  id: number;
  image_path: string;
  auto_status: string | null;
  cover_score: number | null;
  hair_match: boolean | null;
  eye_match: boolean | null;
  gender_pred: string | null;
  is_rejected: boolean;
  is_cover: boolean;
}

export interface CatalogReviewItem {
  id: number;
  series_tag: string;
  series_display_name: string;
  character_tag: string;
  display_name: string;
  post_count: number;
  danbooru_url: string | null;
  danbooru_wiki_url: string | null;
  multi_color_hair: string | null;
  hair_color: string | null;
  hair_shape: string | null;
  eye_color: string | null;
  feature_tags: string | null;
  gender: string | null;
  generation_prompt: string | null;
  character_status: string;
  needs_check_reason: string | null;
  review_status: string | null;
  rating: number | null;
  type: string | null;
  final_prompt: string | null;
  cover_image_id: number | null;
  parent_character_tag?: string | null;
  parent_display_name?: string | null;
  is_alternative?: boolean;
  child_count?: number;
  images: CatalogReviewImage[];
}

// CharacterLinkModal이 GlobalCharacter(캐릭터 관리 탭)와 CatalogReviewItem(리뷰 탭) 양쪽에서
// 공통으로 다룰 수 있도록 필요한 필드만 뽑아낸 최소 인터페이스.
export interface LinkableCharacterSummary {
  id: number;
  character_tag: string;
  display_name: string;
  is_alternative: boolean;
  parent_character_tag: string | null;
  parent_display_name: string | null;
  child_count: number;
}

export type CatalogReviewFilterStatus =
  | "pending"
  | "completed"
  | "completed_recent"
  | "all"
  | "needs_check"
  | "triage_fast"
  | "triage_check"
  | "triage_regen";

export interface CatalogReviewListResponse {
  items: CatalogReviewItem[];
  total: number;
  series_id: number;
  series_tag: string;
}

export interface GlobalCatalogReviewListResponse {
  items: CatalogReviewItem[];
  total: number;
}

export interface CatalogReviewCompletePayload {
  cover_image_id?: number | null;
  gender?: string | null;
  rating?: number | null;
  final_prompt?: string | null;
  selected_tags?: string | null;
}

export interface ReviewRegenerateJob {
  job_id: string;
  character_id: number;
  character_tag: string;
  series_tag: string;
  scope: string;
  status: string;
  phase: string;
  message: string;
  current: number;
  total: number;
  error: string | null;
  result: CatalogReviewItem | null;
  started_at: string;
  finished_at: string | null;
}

export interface ReviewRegenerateJobListResponse {
  items: ReviewRegenerateJob[];
}

export interface V2ReviewImage {
  id: number;
  image_path: string;
  auto_status: string | null;
  cover_score: number | null;
  hair_match: boolean | null;
  eye_match: boolean | null;
  gender_pred: string | null;
  quality_status: string | null;
  quality_score: number | null;
  quality_reasons: string | null;
  identity_status: string | null;
  character_confidence: number | null;
  hair_color_confidence: number | null;
  conflicting_character_tag: string | null;
  conflicting_character_confidence: number | null;
  identity_reasons: string | null;
  suggested_multicolor_tags: string[];
  is_provisional: boolean;
  is_rejected: boolean;
  is_cover: boolean;
}

export interface V2ReviewCharacter {
  id: number;
  character_tag: string;
  display_name: string;
  post_count: number;
  danbooru_wiki_url: string | null;
  series_ids: number[];
  series_tags: string[];
  is_alternative: boolean;
  parent_character_id: number | null;
  parent_character_tag: string | null;
  parent_display_name: string | null;
  child_count: number;
  multi_color_hair: string | null;
  hair_color: string | null;
  hair_shape: string | null;
  eye_color: string | null;
  feature_tags: string | null;
  gender: string | null;
  primary_hair_color: string | null;
  primary_hair_needs_review: boolean;
  base_prompt: string | null;
  previous_base_prompt: string | null;
  prompt_modified: boolean;
  first_post_at: string | null;
  generation_status: string;
  generation_attempts: number;
  review_status: string;
  rating: number | null;
  rating_stage: string;
  selected_tags: string | null;
  cover_image_id: number | null;
  preview_image: V2ReviewImage | null;
  images: V2ReviewImage[];
}

export interface V2ReviewCharacterListResponse {
  items: V2ReviewCharacter[];
  total: number;
}

export type V2ReviewStatus = "pending" | "in_progress" | "completed" | "completed_recent";

export interface V2ReviewFilters {
  review_status?: V2ReviewStatus;
  rating?: string;
  quality_status?: string;
  identity_status?: string;
  generation_status?: string;
  gender?: string;
  series_id?: number;
  multicolor?: string;
  prompt_modified?: boolean;
  search?: string;
  skip?: number;
  limit?: number;
}

export interface V2ReviewSavePayload {
  cover_image_id?: number | null;
  gender?: string | null;
  rating?: number | null;
  base_prompt?: string | null;
  selected_tags?: string | null;
}

export interface V2ReviewCompleteResponse {
  id: number;
  review_status: string;
  rating: number | null;
  rating_stage: string;
  gender: string | null;
  base_prompt: string | null;
  previous_base_prompt: string | null;
  selected_tags: string | null;
}

export interface V2ReviewStats {
  total: number;
  pending: number;
  in_progress: number;
  completed: number;
}

export interface V2BulkCompleteItemPayload {
  character_id: number;
  rating: number | null;
  gender?: string | null;
  base_prompt?: string | null;
  selected_tags?: string | null;
  cover_image_id?: number | null;
}

export interface V2BulkCompleteRequest {
  items: V2BulkCompleteItemPayload[];
}

export interface V2BulkCompleteItemResult {
  character_id: number;
  status: string;
  error: string | null;
}

export interface V2BulkCompleteResponse {
  completed: number;
  skipped: number;
  failed: number;
  results: V2BulkCompleteItemResult[];
}

export interface V2GenerationJobState {
  job_id: string;
  kind: "generate" | "regenerate";
  status: string;
  phase: string;
  message: string;
  current: number;
  total: number;
  completed: number;
  failed: number;
  character_tag: string;
  current_character_tag: string;
  character_id: number | null;
  generation_status: string | null;
  generation_attempts: number;
  total_generation_attempts: number;
  prompt_variant_attempts: Record<string, number>;
  image_id: number | null;
  quality_status: string | null;
  quality_reasons: string[];
  identity_status: string | null;
  identity_reasons: string[];
  is_provisional: boolean | null;
  last_failure_reason: string | null;
  errors: Array<Record<string, unknown>>;
  started_at: string;
  finished_at: string | null;
}

export interface DanbooruStatus {
  configured: boolean;
  ready: boolean;
  message: string;
  username?: string;
  verified_via?: string;
  pybooru_version?: string;
  sample_tag?: string | null;
}

export interface CatalogFilters {
  series_tag?: string;
  rating?: number;
  gender?: string;
  type?: string;
  hair_color?: string;
  eye_color?: string;
  feature_tags?: string;
  status?: string;
  has_cover_image?: boolean;
  needs_review?: boolean;
  needs_regen?: boolean;
  search?: string;
  include_hidden_ratings?: boolean;
  has_alternative?: boolean;
  skip?: number;
  limit?: number;
}

export interface CatalogItemUpdatePayload {
  multi_color_hair?: string | null;
  hair_color?: string | null;
  hair_shape?: string | null;
  eye_color?: string | null;
  feature_tags?: string | null;
  gender?: string | null;
  rating?: number | null;
  type?: string | null;
  final_prompt?: string | null;
}

export interface SeriesCreatePayload {
  series_tag: string;
  display_name?: string;
  post_count?: number;
  priority?: number;
  status?: string;
  note?: string | null;
}

export interface SeriesUpdatePayload {
  series_tag?: string;
  display_name?: string;
  post_count?: number;
  priority?: number;
  status?: string;
  note?: string | null;
}

export interface PipelineStatus {
  status: "idle" | "running" | "stopping" | "completed" | "stopped" | "failed";
  phase:
    | "collecting"
    | "collecting+extracting"
    | "extracting"
    | "extracting+generating"
    | "generating"
    | null;
  collect_total: number;
  collect_done: number;
  collect_failed: number;
  extract_total: number;
  extract_done: number;
  extract_failed: number;
  generate_total: number;
  generate_done: number;
  generate_failed: number;
  auto_generate: boolean;
  current_series_tag: string | null;
  current_job_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  errors: string[];
}
