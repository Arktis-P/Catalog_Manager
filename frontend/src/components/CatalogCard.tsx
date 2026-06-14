import type { CatalogItem } from "../types";

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
  return [item.hair_color, item.hair_shape, item.eye_color, item.feature_tags]
    .filter(Boolean)
    .join(", ");
}

export function CatalogCard({ item, onChangeSeries }: CatalogCardProps) {
  const appearance = formatAppearance(item);
  const meta = [item.gender, item.type, item.rating !== null ? `rating ${item.rating}` : null]
    .filter(Boolean)
    .join(" / ");

  const copyPrompt = async () => {
    if (!item.final_prompt) return;
    await navigator.clipboard.writeText(item.final_prompt);
  };

  return (
    <article className="catalog-card">
      <div className="catalog-card-image">
        {item.cover_image ? (
          <img src={item.cover_image} alt={item.display_name} />
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
        <div className="card-actions">
          <button className="btn btn-small" type="button" onClick={copyPrompt} disabled={!item.final_prompt}>
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
          <button className="btn btn-small" type="button" disabled title="Review Tool (Phase 3)">
            Review
          </button>
          <button className="btn btn-small" type="button" disabled title="Generation Connector (Phase 2)">
            Regenerate
          </button>
        </div>
      </div>
    </article>
  );
}
