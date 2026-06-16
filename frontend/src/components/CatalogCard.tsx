import { Link } from "react-router-dom";
import type { CatalogItem } from "../types";
import { catalogCoverImageUrl } from "../utils/reviewImages";

interface CatalogCardProps {
  item: CatalogItem;
  onChangeSeries?: (item: CatalogItem) => void;
}

function statusBadgeClass(status: string): string {
  if (status === "completed") return "badge badge-success";
  if (status === "needs_review" || status === "missing_image") return "badge badge-warning";
  return "badge badge-muted";
}

function formatAppearance(item: CatalogItem): string {
  return [item.multi_color_hair, item.hair_color, item.hair_shape, item.eye_color, item.feature_tags]
    .filter(Boolean)
    .join(", ");
}

export function CatalogCard({ item, onChangeSeries }: CatalogCardProps) {
  const appearance = formatAppearance(item);
  const meta = [item.gender, item.type, item.rating !== null ? `rating ${item.rating}` : null]
    .filter(Boolean)
    .join(" / ");
  const promptToCopy = item.generation_prompt || item.final_prompt;
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
          <span className="badge">{item.character_status}</span>
          <span className="badge">{item.post_count.toLocaleString()} posts</span>
        </div>
        {meta ? <div className="catalog-card-subtitle">{meta}</div> : null}
        {appearance ? <div className="catalog-card-subtitle">{appearance}</div> : null}
        {item.generation_prompt ? (
          <div className="catalog-card-subtitle" title={item.generation_prompt}>
            prompt: {item.generation_prompt}
          </div>
        ) : null}
        <div className="card-actions">
          <button className="btn btn-small" type="button" onClick={copyPrompt} disabled={!promptToCopy}>
            Prompt Copy
          </button>
          {onChangeSeries ? (
            <button className="btn btn-small" type="button" onClick={() => onChangeSeries(item)}>
              Change Series
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
          <button className="btn btn-small" type="button" disabled title="Generation Connector (Phase 2)">
            Regenerate
          </button>
        </div>
      </div>
    </article>
  );
}
