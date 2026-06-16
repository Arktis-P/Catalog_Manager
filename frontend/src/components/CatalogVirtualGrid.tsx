import { useEffect, useRef, useState } from "react";
import type { CatalogItem } from "../types";
import { CatalogCard } from "./CatalogCard";

const CARD_MIN_WIDTH = 280;
const ROW_HEIGHT = 560;
const ROW_GAP = 16;
const OVERSCAN_ROWS = 1;

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
  const scrollRef = useRef<HTMLDivElement>(null);
  const [columnCount, setColumnCount] = useState(4);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(720);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) {
      return;
    }

    const resize = () => {
      const width = node.clientWidth;
      setColumnCount(Math.max(1, Math.floor((width + ROW_GAP) / (CARD_MIN_WIDTH + ROW_GAP))));
      setViewportHeight(node.clientHeight);
    };

    const onScroll = () => setScrollTop(node.scrollTop);
    resize();
    node.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", resize);
    const observer = new ResizeObserver(resize);
    observer.observe(node);

    return () => {
      node.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", resize);
      observer.disconnect();
    };
  }, []);

  const rowStride = ROW_HEIGHT + ROW_GAP;
  const rowCount = Math.max(1, Math.ceil(items.length / columnCount));
  const totalHeight = Math.max(0, rowCount * rowStride - ROW_GAP);

  const startRow = Math.max(0, Math.floor(scrollTop / rowStride) - OVERSCAN_ROWS);
  const visibleRows = Math.ceil(viewportHeight / rowStride) + OVERSCAN_ROWS * 2;
  const endRow = Math.min(rowCount, startRow + visibleRows);

  useEffect(() => {
    if (loading || loadingMore || items.length >= total) {
      return;
    }
    const visibleEndIndex = endRow * columnCount;
    if (visibleEndIndex >= items.length - columnCount) {
      onLoadMore();
    }
  }, [columnCount, endRow, items.length, loading, loadingMore, onLoadMore, total]);

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

  const visibleRowsList = Array.from({ length: endRow - startRow }, (_, index) => startRow + index);

  return (
    <div ref={scrollRef} className="catalog-virtual-scroll">
      <div className="catalog-virtual-spacer" style={{ height: totalHeight }}>
        <div className="catalog-virtual-window" style={{ transform: `translateY(${startRow * rowStride}px)` }}>
          {visibleRowsList.map((row) => (
            <div
              key={row}
              className="catalog-virtual-row"
              style={{ height: ROW_HEIGHT, marginBottom: ROW_GAP, gridTemplateColumns: `repeat(${columnCount}, 1fr)` }}
            >
              {Array.from({ length: columnCount }, (_, col) => {
                const index = row * columnCount + col;
                const item = items[index];
                if (!item) {
                  return <div key={`empty-${row}-${col}`} />;
                }
                return (
                  <CatalogCard
                    key={item.id}
                    item={item}
                    onEdit={onEdit}
                    onChangeSeries={onChangeSeries}
                    onRegenerate={onRegenerate}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
      {loadingMore ? <div className="catalog-loading-more">Loading more...</div> : null}
      <div className="pagination-bar">
        <span className="catalog-card-subtitle">
          {items.length.toLocaleString()} / {total.toLocaleString()} loaded
        </span>
      </div>
    </div>
  );
}
