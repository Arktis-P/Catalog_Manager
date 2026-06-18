import { useState } from "react";
import { api } from "../api/client";
import type { CatalogFilters, CatalogItem } from "../types";
import { catalogCoverImageUrl } from "../utils/reviewImages";

interface CatalogRandomPanelProps {
  filters: Omit<CatalogFilters, "skip" | "limit">;
}

function formatMeta(item: CatalogItem): string {
  return [
    item.gender,
    item.type,
    item.rating !== null ? `rating ${item.rating}` : null,
    `${item.post_count.toLocaleString()} posts`,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function CatalogRandomPanel({ filters }: CatalogRandomPanelProps) {
  const [item, setItem] = useState<CatalogItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickRandom = async () => {
    setLoading(true);
    setError(null);
    try {
      const randomItem = await api.getRandomCatalogCharacter(filters);
      setItem(randomItem);
    } catch (err) {
      setItem(null);
      setError(err instanceof Error ? err.message : "Failed to load random character");
    } finally {
      setLoading(false);
    }
  };

  const coverUrl =
    item && item.rating !== 0 ? catalogCoverImageUrl(item.cover_image, 512) : null;

  return (
    <section className="panel catalog-random-panel">
      <div className="catalog-random-header">
        <div>
          <h2 className="catalog-section-title">Random Character</h2>
          <p className="catalog-card-subtitle">
            현재 필터 범위에서 rating 가중치 기반으로 무작위 캐릭터를 표시합니다. (가중치는 추후 Settings에서 조정 예정)
          </p>
        </div>
        <button className="btn btn-primary" type="button" disabled={loading} onClick={() => void pickRandom()}>
          {loading ? "Loading..." : item ? "다른 캐릭터" : "랜덤 뽑기"}
        </button>
      </div>
      {error ? <div className="error-banner">{error}</div> : null}
      {item ? (
        <div className="catalog-random-body">
          <div className="catalog-random-image">
            {coverUrl ? (
              <img src={coverUrl} alt={item.display_name} />
            ) : item.rating === 0 ? (
              <span className="catalog-card-image-failed">Image generation failed</span>
            ) : (
              <span>No cover image</span>
            )}
          </div>
          <div className="catalog-random-info">
            <h3 className="catalog-card-title">{item.character_tag}</h3>
            <div className="catalog-card-subtitle">{item.series_display_name || item.series_tag}</div>
            <div className="tag-row">
              <span className="badge">{item.catalog_status}</span>
              <span className="badge">{item.character_status}</span>
            </div>
            <div className="catalog-card-subtitle">{formatMeta(item)}</div>
            {item.final_prompt || item.generation_prompt ? (
              <div className="catalog-random-prompt" title={item.final_prompt || item.generation_prompt || undefined}>
                {item.final_prompt || item.generation_prompt}
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="empty-state">랜덤 뽑기를 눌러 캐릭터를 확인하세요.</div>
      )}
    </section>
  );
}
