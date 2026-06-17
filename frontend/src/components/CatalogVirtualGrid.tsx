import { useEffect, useRef } from "react";
import type { CatalogItem } from "../types";
import { CatalogCard } from "./CatalogCard";

interface CatalogVirtualGridProps {
  items: CatalogItem[];
  total: number;
  loading: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  onEdit: (item: CatalogItem) => void;
  onChangeSeries: (item: CatalogItem) => void;
  onRegenerate: (item: CatalogItem) => void;
}

export function CatalogVirtualGrid({
  items,
  total,
  loading,
  loadingMore,
  onLoadMore,
  onEdit,
  onChangeSeries,
  onRegenerate,
}: CatalogVirtualGridProps) {
  const sentinelRef = useRef<HTMLDivElement>(null);
  const hasMore = items.length < total;

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasMore || loading || loadingMore) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          onLoadMore();
        }
      },
      { rootMargin: "480px 0px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, loading, loadingMore, onLoadMore, items.length]);

  if (loading && items.length === 0) {
    return <div className="empty-state">Loading catalog...</div>;
  }

  if (!loading && items.length === 0) {
    return (
      <div className="empty-state">
        표시할 캐릭터가 없습니다. Series를 추가하거나 Character Collector를 실행하세요.
      </div>
    );
  }

  return (
    <div className="catalog-grid-wrap">
      <div className="catalog-grid">
        {items.map((item) => (
          <CatalogCard
            key={item.id}
            item={item}
            onEdit={onEdit}
            onChangeSeries={onChangeSeries}
            onRegenerate={onRegenerate}
          />
        ))}
      </div>
      {hasMore ? <div ref={sentinelRef} className="catalog-load-sentinel" aria-hidden /> : null}
      {loadingMore ? <div className="catalog-loading-more">Loading more...</div> : null}
      <div className="pagination-bar">
        <span className="catalog-card-subtitle">
          {items.length.toLocaleString()} / {total.toLocaleString()} loaded
        </span>
      </div>
    </div>
  );
}
