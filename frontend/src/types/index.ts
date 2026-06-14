export interface Series {
  id: number;
  series_tag: string;
  display_name: string;
  post_count: number;
  priority: number;
  status: string;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface SeriesListResponse {
  items: Series[];
  total: number;
}

export interface CatalogItem {
  id: number;
  series_tag: string;
  series_display_name: string;
  character_tag: string;
  display_name: string;
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
