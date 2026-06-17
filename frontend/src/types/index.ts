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
}

export interface CatalogListResponse {
  items: CatalogItem[];
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
  images: CatalogReviewImage[];
}

export interface CatalogReviewListResponse {
  items: CatalogReviewItem[];
  total: number;
  series_id: number;
  series_tag: string;
}

export interface CatalogReviewCompletePayload {
  cover_image_id: number;
  gender?: string | null;
  rating?: number | null;
  final_prompt?: string | null;
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
