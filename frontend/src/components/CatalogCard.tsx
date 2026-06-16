import { Link } from "react-router-dom";
import type { CatalogItem } from "../types";
import { catalogCoverImageUrl } from "../utils/reviewImages";

interface CatalogCardProps {
  item: CatalogItem;
  onEdit?: (item: CatalogItem) => void;
  onChangeSeries?: (item: CatalogItem) => void;
  onRegenerate?: (item: CatalogItem) => void;
}

function statusBadgeClass(status: string): string {
  if (status === "completed") return "badge badge-success";
  if (status === "needs_regen") return "badge badge-warning";
  if (status === "needs_review" || status === "missing_image" || status === "tag_needs_check") {
    return "badge badge-warning";
  }
  if (status === "excluded") return "badge badge-muted";
  return "badge badge-muted";
}

function ratingLabel(rating: number | null): string | null {
  if (rating === null) return null;
  if (rating === -1) return "rating -1";
  return `rating ${"★".repeat(rating)}${"☆".repeat(Math.max(0, 6 - rating))}`;
}

function formatAppearance(item: CatalogItem): string {
  return [item.multi_color_hair, item.hair_color, item.hair_shape, item.eye_color, item.feature_tags]
    .filter(Boolean)
    .join(", ");
}

export function CatalogCard({ item, onEdit, onChangeSeries, onRegenerate }: CatalogCardProps) {
  const appearance = formatAppearance(item);
  const ratingText = ratingLabel(item.rating);
  const meta = [item.gender, item.type, ratingText].filter(Boolean).join(" / ");
  const promptToCopy = item.final_prompt || item.generation_prompt;
  const coverUrl = catalogCoverImageUrl(item.cover_image);

  const copyPrompt = async () => {
    if (!promptToCopy) return;
    await navigator.clipboard.writeText(promptToCopy);
  };

  return (
    <article className="catalog-card">
      <div className="catalog-card-image">
        {coverUrl ? (
          <img src={coverUrl} alt={item.display_name} loading="lazy" decoding="async" />
        ) : (
          <span>No cover image</span>
        )}
      </div>
      <div className="catalog-card-body">
        <div>
          <h3 className="catalog-card-title">{item.character_tag}</h3>
          <div className="catalog-card-subtitle">{item.series_display_name || item.series_tag}</div>
        </div>
        <div className="tag-row">
          <span className={statusBadgeClass(item.catalog_status)}>{item.catalog_status}</span>
          {item.needs_regen ? <span className="badge badge-warning">needs_regen</span> : null}
          {item.needs_review ? <span className="badge">needs_review</span> : null}
          <span className="badge badge-muted">{item.character_status}</span>
          <span className="badge">{item.post_count.toLocaleString()} posts</span>
        </div>
        {meta ? <div className="catalog-card-subtitle">{meta}</div> : null}
        {appearance ? <div className="catalog-card-subtitle">{appearance}</div> : null}
        {promptToCopy ? (
          <div className="catalog-card-subtitle catalog-card-prompt" title={promptToCopy}>
            {promptToCopy}
          </div>
        ) : null}
        <div className="card-actions">
          {onEdit ? (
            <button className="btn btn-small" type="button" onClick={() => onEdit(item)}>
              Edit
            </button>
          ) : null}
          <button className="btn btn-small" type="button" onClick={() => void copyPrompt()} disabled={!promptToCopy}>
            Copy Prompt
          </button>
          {onChangeSeries ? (
            <button className="btn btn-small" type="button" onClick={() => onChangeSeries(item)}>
              Series
            </button>
          ) : null}
          {item.danbooru_url ? (
            <a className="btn btn-small" href={item.danbooru_url} target="_blank" rel="noreferrer">
              Danbooru
            </a>
          ) : null}
          <Link
            className="btn btn-small"
            to={`/review?mode=catalog&series_id=${item.series_id}&character_id=${item.id}`}
          >
            Review
          </Link>
          {onRegenerate ? (
            <button className="btn btn-small" type="button" onClick={() => onRegenerate(item)}>
              Regen
            </button>
          ) : null}
        </div>
      </div>
    </article>
  );
}
