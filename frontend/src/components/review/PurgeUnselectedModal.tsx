import { useEffect, useMemo, useState } from "react";
import type {
  CatalogReviewPurgePreviewItem,
  CatalogReviewPurgePreviewResponse,
  CatalogReviewPurgeSelectedResult,
} from "../../types";
import { pendingReviewImageUrl } from "../../utils/reviewImages";

const DETAIL_THUMB_SIZE = 480;

interface PurgeUnselectedModalProps {
  title: string;
  description?: string;
  fetchPreview: () => Promise<CatalogReviewPurgePreviewResponse>;
  onSubmit: (characterIds: number[]) => Promise<CatalogReviewPurgeSelectedResult>;
  onClose: () => void;
  onCompleted: (result: CatalogReviewPurgeSelectedResult) => void;
}

export function PurgeUnselectedModal({
  title,
  description,
  fetchPreview,
  onSubmit,
  onClose,
  onCompleted,
}: PurgeUnselectedModalProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<CatalogReviewPurgePreviewItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [focusedId, setFocusedId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchPreview()
      .then((response) => {
        if (cancelled) return;
        setItems(response.items);
        setSelectedIds(new Set(response.items.map((item) => item.character_id)));
        setFocusedId(response.items[0]?.character_id ?? null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "미리보기를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchPreview]);

  const handleClose = () => {
    if (submitting) return;
    onClose();
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        handleClose();
      }
    };
    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submitting]);

  const focusedItem = useMemo(
    () => items.find((item) => item.character_id === focusedId) ?? null,
    [items, focusedId],
  );

  const selectedCharacterCount = selectedIds.size;
  const selectedImageCount = useMemo(
    () =>
      items.reduce(
        (sum, item) => (selectedIds.has(item.character_id) ? sum + item.delete_images.length : sum),
        0,
      ),
    [items, selectedIds],
  );

  const toggleItem = (characterId: number) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(characterId)) {
        next.delete(characterId);
      } else {
        next.add(characterId);
      }
      return next;
    });
    setFocusedId(characterId);
  };

  const selectAll = () => setSelectedIds(new Set(items.map((item) => item.character_id)));
  const clearAll = () => setSelectedIds(new Set());

  const handleSubmit = async () => {
    if (selectedCharacterCount === 0 || submitting) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await onSubmit(Array.from(selectedIds));
      onCompleted(result);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "미선택 이미지 삭제에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={handleClose}>
      <div
        className="modal modal-wide purge-unselected-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-header-row">
          <div className="modal-header-copy">
            <h2 className="modal-title">{title}</h2>
            {description ? <p className="catalog-card-subtitle">{description}</p> : null}
          </div>
          <button className="btn btn-small" type="button" disabled={submitting} onClick={handleClose}>
            Close
          </button>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}

        {loading ? (
          <div className="empty-state">미리보기 불러오는 중...</div>
        ) : items.length === 0 ? (
          <div className="empty-state panel">삭제할 미선택 이미지가 없습니다.</div>
        ) : (
          <>
            <div className="purge-unselected-toolbar">
              <span className="catalog-card-subtitle">
                {items.length.toLocaleString()}개 캐릭터 · 선택됨 {selectedCharacterCount.toLocaleString()}개 · 삭제
                예정 이미지 {selectedImageCount.toLocaleString()}장
              </span>
              <div className="purge-unselected-toolbar-actions">
                <button className="btn btn-small" type="button" onClick={selectAll} disabled={submitting}>
                  전체 선택
                </button>
                <button className="btn btn-small" type="button" onClick={clearAll} disabled={submitting}>
                  전체 해제
                </button>
              </div>
            </div>

            <div className="purge-unselected-body">
              <div className="purge-unselected-list" role="listbox" aria-label="삭제 후보 목록">
                {items.map((item) => {
                  const checked = selectedIds.has(item.character_id);
                  const focused = item.character_id === focusedId;
                  return (
                    <div
                      key={item.character_id}
                      role="option"
                      aria-selected={focused}
                      aria-disabled={submitting}
                      tabIndex={submitting ? -1 : 0}
                      className={`purge-unselected-item${focused ? " purge-unselected-item--focused" : ""}`}
                      onClick={() => {
                        if (submitting) return;
                        setFocusedId(item.character_id);
                      }}
                      onKeyDown={(event) => {
                        if (submitting) return;
                        if (event.key === "Enter") {
                          setFocusedId(item.character_id);
                        } else if (event.key === " ") {
                          event.preventDefault();
                          setFocusedId(item.character_id);
                        }
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        aria-label={`${item.character_tag} 선택`}
                        onClick={(event) => event.stopPropagation()}
                        onChange={() => toggleItem(item.character_id)}
                        disabled={submitting}
                      />
                      <span className="purge-unselected-item-tag">{item.character_tag}</span>
                      <span className="purge-unselected-item-meta">
                        ★{item.rating} · 삭제 {item.delete_images.length}장
                      </span>
                    </div>
                  );
                })}
              </div>

              <div className="purge-unselected-detail">
                {focusedItem ? (
                  <>
                    <h3 className="purge-unselected-detail-title">
                      {focusedItem.display_name || focusedItem.character_tag}
                    </h3>

                    <div className="purge-unselected-detail-section">
                      <div className="purge-unselected-detail-label">보존될 선택 이미지</div>
                      {focusedItem.selected_image ? (
                        <div className="purge-unselected-thumb-row">
                          <img
                            className="purge-unselected-thumb purge-unselected-thumb--keep"
                            src={
                              pendingReviewImageUrl(focusedItem.selected_image.image_path, {
                                thumbnail: true,
                                thumbSize: DETAIL_THUMB_SIZE,
                              }) ?? undefined
                            }
                            alt={`${focusedItem.character_tag} 보존 이미지`}
                          />
                        </div>
                      ) : (
                        <div className="catalog-card-subtitle">
                          보존할 이미지가 없습니다 (rating {focusedItem.rating}).
                        </div>
                      )}
                    </div>

                    <div className="purge-unselected-detail-section">
                      <div className="purge-unselected-detail-label">
                        삭제될 이미지 ({focusedItem.delete_images.length}장)
                      </div>
                      {focusedItem.delete_images.length > 0 ? (
                        <div className="purge-unselected-thumb-row">
                          {focusedItem.delete_images.map((image) => (
                            <img
                              key={image.id}
                              className="purge-unselected-thumb purge-unselected-thumb--delete"
                              src={
                                pendingReviewImageUrl(image.image_path, {
                                  thumbnail: true,
                                  thumbSize: DETAIL_THUMB_SIZE,
                                }) ?? undefined
                              }
                              alt={`${focusedItem.character_tag} 삭제 예정 이미지`}
                            />
                          ))}
                        </div>
                      ) : (
                        <div className="catalog-card-subtitle">삭제할 이미지가 없습니다.</div>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="empty-state">항목을 선택하세요.</div>
                )}
              </div>
            </div>
          </>
        )}

        <div className="modal-actions purge-unselected-actions">
          <span className="purge-unselected-warning">이 작업은 되돌릴 수 없습니다.</span>
          <button className="btn" type="button" onClick={handleClose} disabled={submitting}>
            Cancel
          </button>
          <button
            className="btn btn-danger"
            type="button"
            disabled={submitting || selectedCharacterCount === 0 || items.length === 0}
            onClick={() => void handleSubmit()}
          >
            {submitting
              ? "삭제 중..."
              : `선택한 ${selectedCharacterCount}개 캐릭터의 이미지 ${selectedImageCount}장 삭제`}
          </button>
        </div>
      </div>
    </div>
  );
}
