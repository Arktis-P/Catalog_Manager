import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  applyParentChildGroup,
  getParentChildGroup,
  listParentChildGroups,
  type ParentChildApplyConflict,
  type ParentChildCandidate,
  type ParentChildGroup,
} from "../../api/reviewPipeline";
import { pendingReviewImageUrl } from "../../utils/reviewImages";
import { SeriesSearchSelect } from "../SeriesSearchSelect";
import type { Series } from "../../types";
import { LazyReviewImage } from "./LazyReviewImage";
import { ReviewImagePreview } from "./ReviewImagePreview";
import "./reviewPipeline.css";

const PAGE_SIZE = 20;
const CONFLICT_FIELDS = ["gender", "primary_hair_color", "hair_color", "hair_shape", "eye_color"] as const;

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
}

function humanizeTag(tag: string): string {
  return tag.replace(/_/g, " ");
}

function fieldsConflict(parent: ParentChildCandidate, child: ParentChildCandidate): string[] {
  const conflicts: string[] = [];
  for (const field of CONFLICT_FIELDS) {
    const parentValue = parent[field];
    const childValue = child[field];
    if (parentValue && childValue && parentValue !== childValue) {
      conflicts.push(field);
    }
  }
  return conflicts;
}

interface ParentChildOptions {
  inheritTags: boolean;
  applyParentRating: boolean;
  completeChildren: boolean;
  completeParent: boolean;
}

const DEFAULT_OPTIONS: ParentChildOptions = {
  inheritTags: true,
  applyParentRating: false,
  completeChildren: false,
  completeParent: false,
};

interface ApplyOutcome {
  message: string;
  conflicts: ParentChildApplyConflict[];
}

export function ParentChildReviewPanel() {
  const gridRef = useRef<HTMLDivElement>(null);
  const [groups, setGroups] = useState<ParentChildGroup[]>([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [seriesId, setSeriesId] = useState<number | "">("");
  const [confidence, setConfidence] = useState<"all" | "medium" | "high">("all");
  const [alreadyLinkedOnly, setAlreadyLinkedOnly] = useState(false);
  const [unreviewedFirst, setUnreviewedFirst] = useState(true);

  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);
  const [checkedIds, setCheckedIds] = useState<Set<number>>(() => new Set());
  const [options, setOptions] = useState<ParentChildOptions>(DEFAULT_OPTIONS);
  const [focusIndex, setFocusIndex] = useState(-1); // -1 = parent card focused
  const [gridCols, setGridCols] = useState(1);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyOutcome, setApplyOutcome] = useState<ApplyOutcome | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  const activeGroup = useMemo(() => groups.find((group) => group.group_id === activeGroupId) ?? null, [
    groups,
    activeGroupId,
  ]);

  const loadControllerRef = useRef<AbortController | null>(null);
  const loadRequestIdRef = useRef(0);

  const loadGroups = useCallback(async () => {
    loadControllerRef.current?.abort();
    const controller = new AbortController();
    loadControllerRef.current = controller;
    const requestId = (loadRequestIdRef.current += 1);
    setLoading(true);
    setError(null);
    try {
      const response = await listParentChildGroups(
        {
          series_id: seriesId || undefined,
          search: search || undefined,
          confidence,
          already_linked_only: alreadyLinkedOnly,
          unreviewed_first: unreviewedFirst,
          skip,
          limit: PAGE_SIZE,
        },
        controller.signal,
      );
      if (loadRequestIdRef.current !== requestId) {
        // A newer request superseded this one; discard the stale result.
        return;
      }
      setGroups(response.items);
      setTotal(response.total);
      setActiveGroupId((current) => {
        if (current && response.items.some((group) => group.group_id === current)) {
          return current;
        }
        return response.items[0]?.group_id ?? null;
      });
    } catch (err) {
      if (controller.signal.aborted || loadRequestIdRef.current !== requestId) {
        return;
      }
      setError(err instanceof Error ? err.message : "부모-자식 그룹 목록을 불러오지 못했습니다.");
    } finally {
      if (loadRequestIdRef.current === requestId) {
        setLoading(false);
      }
    }
  }, [seriesId, search, confidence, alreadyLinkedOnly, unreviewedFirst, skip]);

  useEffect(() => {
    void loadGroups();
    return () => {
      loadControllerRef.current?.abort();
    };
  }, [loadGroups]);

  useEffect(() => {
    setSkip(0);
  }, [seriesId, search, confidence, alreadyLinkedOnly, unreviewedFirst]);

  useEffect(() => {
    if (!activeGroup) {
      setCheckedIds(new Set());
      return;
    }
    setCheckedIds(
      new Set(
        activeGroup.children
          .filter((child) => child.already_linked || child.default_selected)
          .map((child) => child.id),
      ),
    );
    setFocusIndex(-1);
    setApplyOutcome(null);
    setApplyError(null);
    setOptions(DEFAULT_OPTIONS);
  }, [activeGroup]);

  useEffect(() => {
    const node = gridRef.current;
    if (!node) {
      return;
    }
    const measure = () => {
      const style = window.getComputedStyle(node);
      const cols = style.gridTemplateColumns.split(" ").filter(Boolean).length;
      setGridCols(Math.max(1, cols));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [activeGroup?.group_id]);

  const toggleChecked = useCallback((childId: number) => {
    setCheckedIds((current) => {
      const next = new Set(current);
      if (next.has(childId)) {
        next.delete(childId);
      } else {
        next.add(childId);
      }
      return next;
    });
  }, []);

  const refreshActiveGroup = useCallback(async () => {
    if (!activeGroupId) {
      return;
    }
    try {
      const refreshed = await getParentChildGroup(activeGroupId, confidence);
      setGroups((current) => current.map((group) => (group.group_id === activeGroupId ? refreshed : group)));
    } catch {
      await loadGroups();
    }
  }, [activeGroupId, confidence, loadGroups]);

  const applyActiveGroup = useCallback(async () => {
    if (!activeGroup || applying) {
      return;
    }
    const selectedChildIds = activeGroup.children.filter((child) => checkedIds.has(child.id)).map((child) => child.id);
    const unlinkChildIds = activeGroup.children
      .filter((child) => child.already_linked && !checkedIds.has(child.id))
      .map((child) => child.id);

    setApplying(true);
    setApplyError(null);
    setApplyOutcome(null);
    try {
      const result = await applyParentChildGroup(activeGroup.group_id, {
        selected_child_ids: selectedChildIds,
        unlink_child_ids: unlinkChildIds,
        inherit_tags: options.inheritTags,
        apply_parent_rating: options.applyParentRating,
        complete_children: options.completeChildren,
        complete_parent: options.completeParent,
      });
      setApplyOutcome({
        message: `연결 ${result.linked_child_ids.length}건 · 해제 ${result.unlinked_child_ids.length}건${
          result.parent_completed ? " · 부모 완료" : ""
        }`,
        conflicts: result.conflicts,
      });
      await refreshActiveGroup();
    } catch (err) {
      setApplyError(err instanceof Error ? err.message : "적용에 실패했습니다.");
    } finally {
      setApplying(false);
    }
  }, [activeGroup, applying, checkedIds, options, refreshActiveGroup]);

  const focusedChild: ParentChildCandidate | null =
    activeGroup && focusIndex >= 0 ? activeGroup.children[focusIndex] ?? null : null;
  const focusedItem: ParentChildCandidate | null = focusIndex === -1 ? activeGroup?.parent ?? null : focusedChild;
  const previewSrc = focusedItem?.preview_image ? pendingReviewImageUrl(focusedItem.preview_image.image_path) : null;

  useEffect(() => {
    if (!previewSrc) {
      setPreviewOpen(false);
    }
  }, [previewSrc]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target) || !activeGroup) {
        return;
      }
      const childCount = activeGroup.children.length;

      if (event.key === " " || event.code === "Space") {
        event.preventDefault();
        if (previewSrc) {
          setPreviewOpen((open) => !open);
        }
        return;
      }

      if (previewOpen) {
        // The image preview dialog owns keyboard input (Escape/Tab) while open;
        // background destructive/rating/arrow shortcuts must not also fire.
        return;
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setFocusIndex((index) => Math.max(-1, index - 1));
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        setFocusIndex((index) => Math.min(childCount - 1, index + 1));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setFocusIndex((index) => (index <= -1 ? -1 : Math.max(-1, index - gridCols)));
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setFocusIndex((index) => {
          if (index === -1) {
            return childCount > 0 ? 0 : -1;
          }
          return Math.min(childCount - 1, index + gridCols);
        });
        return;
      }

      const key = event.key.toLowerCase();
      if (key === "a") {
        event.preventDefault();
        if (focusedChild) {
          toggleChecked(focusedChild.id);
        }
        return;
      }

      if (event.key === "Enter") {
        event.preventDefault();
        void applyActiveGroup();
      }
    };

    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [activeGroup, focusedChild, gridCols, previewOpen, previewSrc, applyActiveGroup, toggleChecked]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(skip / PAGE_SIZE) + 1;

  return (
    <>
      <div className="toolbar review-toolbar">
        <div className="field">
          <label htmlFor="pc-search">검색</label>
          <input id="pc-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="character tag" />
        </div>
        <div className="field review-series-field">
          <label>시리즈</label>
          <SeriesSearchSelect value={seriesId} onChange={(id: number | "", _series?: Series | null) => setSeriesId(id)} />
        </div>
        <div className="field">
          <label htmlFor="pc-confidence">신뢰도</label>
          <select
            id="pc-confidence"
            value={confidence}
            onChange={(event) => setConfidence(event.target.value as "all" | "medium" | "high")}
          >
            <option value="all">전체</option>
            <option value="medium">medium 이상</option>
            <option value="high">high만</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="pc-already-linked">&nbsp;</label>
          <label className="review-checkbox-field">
            <input
              id="pc-already-linked"
              type="checkbox"
              checked={alreadyLinkedOnly}
              onChange={(event) => setAlreadyLinkedOnly(event.target.checked)}
            />
            이미 연결된 그룹만
          </label>
        </div>
        <div className="field">
          <label htmlFor="pc-unreviewed-first">&nbsp;</label>
          <label className="review-checkbox-field">
            <input
              id="pc-unreviewed-first"
              type="checkbox"
              checked={unreviewedFirst}
              onChange={(event) => setUnreviewedFirst(event.target.checked)}
            />
            미검수 우선
          </label>
        </div>
        <div className="field" style={{ justifyContent: "flex-end" }}>
          <label>&nbsp;</label>
          <button className="btn" type="button" onClick={() => void loadGroups()}>
            새로고침
          </button>
        </div>
        <div className="rp-panel-summary">
          <span>총 {total.toLocaleString()}개 그룹 · 페이지 {currentPage}/{pageCount}</span>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      {loading ? (
        <div className="empty-state">그룹을 불러오는 중...</div>
      ) : groups.length === 0 ? (
        <div className="empty-state panel">자식 후보가 있는 부모 그룹이 없습니다.</div>
      ) : (
        <div className="pc-layout">
          <div className="pc-group-list" aria-label="부모-자식 그룹 목록">
            {groups.map((group) => (
              <button
                key={group.group_id}
                type="button"
                className={`pc-group-list-item${group.group_id === activeGroupId ? " pc-group-list-item--active" : ""}`}
                onClick={() => setActiveGroupId(group.group_id)}
              >
                <span>{humanizeTag(group.parent.display_name || group.parent.character_tag)}</span>
                <span className="pc-confidence">
                  자식 {group.candidate_count} · 선택 {group.selected_count}
                  {group.conflict_count > 0 ? ` · 충돌 ${group.conflict_count}` : ""}
                </span>
              </button>
            ))}
          </div>

          {activeGroup ? (
            <div className="pc-group-body">
              <article
                className={`pc-parent-card${focusIndex === -1 ? " pc-child-card--focused" : ""}`}
                tabIndex={-1}
                aria-label={`부모: ${activeGroup.parent.display_name}`}
              >
                <div className="pc-card-image">
                  {activeGroup.parent.preview_image ? (
                    <LazyReviewImage
                      imagePath={activeGroup.parent.preview_image.image_path}
                      alt={activeGroup.parent.character_tag}
                      active={focusIndex === -1}
                      eager
                      thumbSize={256}
                    />
                  ) : (
                    <div className="pc-card-image--empty">No image</div>
                  )}
                </div>
                <div className="pc-card-body">
                  <div className="pc-card-title-row">
                    <h3 className="pc-card-title">{humanizeTag(activeGroup.parent.display_name)}</h3>
                    <span className="badge">{activeGroup.parent.post_count.toLocaleString()} posts</span>
                    <span className="badge badge-muted">부모</span>
                  </div>
                  <div className="catalog-card-subtitle">{activeGroup.parent.character_tag}</div>
                  <div className="pc-card-reasons">
                    {activeGroup.reasons.map((reason) => (
                      <span key={reason} className="pc-reason-chip">
                        {reason}
                      </span>
                    ))}
                  </div>
                </div>
              </article>

              {applyOutcome && applyOutcome.conflicts.length > 0 ? (
                <div className="pc-conflict-banner">
                  필드 충돌 {applyOutcome.conflicts.length}건:{" "}
                  {applyOutcome.conflicts
                    .map((conflict) => `#${conflict.child_id} ${conflict.field} (${conflict.parent_value ?? "-"} vs ${conflict.child_value ?? "-"})`)
                    .join(", ")}
                </div>
              ) : null}
              {applyError ? <div className="error-banner rp-error">{applyError}</div> : null}
              {applyOutcome ? <div className="catalog-card-subtitle">{applyOutcome.message}</div> : null}

              <div ref={gridRef} className="pc-child-grid" role="grid" aria-label="자식 후보 목록">
                {activeGroup.children.map((child, index) => {
                  const checked = checkedIds.has(child.id);
                  const conflicts = fieldsConflict(activeGroup.parent, child);
                  const focused = index === focusIndex;
                  return (
                    <article
                      key={child.id}
                      data-row-index={index}
                      tabIndex={focused ? 0 : -1}
                      className={`pc-child-card${focused ? " pc-child-card--focused" : ""}${
                        checked ? " pc-child-card--selected" : ""
                      }${conflicts.length > 0 ? " pc-child-card--conflict" : ""}${
                        child.already_linked ? " pc-child-card--already-linked" : ""
                      }`}
                      onMouseDown={() => setFocusIndex(index)}
                      onFocus={() => setFocusIndex(index)}
                      aria-selected={checked}
                    >
                      <div className="pc-card-image">
                        {child.preview_image ? (
                          <LazyReviewImage
                            imagePath={child.preview_image.image_path}
                            alt={child.character_tag}
                            active={focused}
                            eager
                            thumbSize={192}
                          />
                        ) : (
                          <div className="pc-card-image--empty">No image</div>
                        )}
                      </div>
                      <div className="pc-card-body">
                        <div className="pc-card-title-row">
                          <h3 className="pc-card-title">{humanizeTag(child.display_name)}</h3>
                          {child.already_linked ? <span className="badge badge-muted">연결됨</span> : null}
                        </div>
                        <div className="pc-confidence">신뢰도 {(child.confidence * 100).toFixed(0)}%</div>
                        <div className="pc-card-reasons">
                          {child.reasons.map((reason) => (
                            <span key={reason} className="pc-reason-chip">
                              {reason}
                            </span>
                          ))}
                          {conflicts.length > 0 ? (
                            <span className="pc-reason-chip" style={{ color: "var(--warning)" }}>
                              필드 충돌: {conflicts.join(", ")}
                            </span>
                          ) : null}
                        </div>
                        <label className="pc-child-select">
                          <input type="checkbox" checked={checked} onChange={() => toggleChecked(child.id)} />
                          {child.already_linked ? "연결 유지" : "이 그룹에 연결"}
                        </label>
                      </div>
                    </article>
                  );
                })}
              </div>

              <div className="pc-options">
                <label>
                  <input
                    type="checkbox"
                    checked={options.inheritTags}
                    onChange={(event) => setOptions((current) => ({ ...current, inheritTags: event.target.checked }))}
                  />
                  부모 외형 태그 상속 (빈 값만)
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={options.applyParentRating}
                    onChange={(event) =>
                      setOptions((current) => ({ ...current, applyParentRating: event.target.checked }))
                    }
                  />
                  부모 레이팅 적용
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={options.completeChildren}
                    onChange={(event) =>
                      setOptions((current) => ({ ...current, completeChildren: event.target.checked }))
                    }
                  />
                  연결된 자식 리뷰 완료 처리
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={options.completeParent}
                    onChange={(event) => setOptions((current) => ({ ...current, completeParent: event.target.checked }))}
                  />
                  부모 리뷰 완료 처리
                </label>
                <button className="btn btn-primary btn-small" type="button" disabled={applying} onClick={() => void applyActiveGroup()}>
                  {applying ? "적용 중..." : "적용 (Enter)"}
                </button>
              </div>
              <div className="rp-panel-summary">
                <span>←→↑↓ 카드 이동 · A 선택 토글 · Space 확대 · Enter 적용</span>
              </div>
            </div>
          ) : (
            <div className="empty-state panel">그룹을 선택하세요.</div>
          )}
        </div>
      )}

      {previewOpen && previewSrc && focusedItem ? (
        <ReviewImagePreview
          src={previewSrc}
          alt={focusedItem.character_tag}
          original
          onClose={() => setPreviewOpen(false)}
          characterId={focusedItem.id}
          characterTag={focusedItem.character_tag}
        />
      ) : null}

      {total > PAGE_SIZE ? (
        <div className="series-pagination">
          <div className="series-pagination-controls">
            <button className="btn btn-small" type="button" disabled={skip === 0} onClick={() => setSkip(0)}>
              &laquo;
            </button>
            <button
              className="btn btn-small"
              type="button"
              disabled={skip === 0}
              onClick={() => setSkip((s) => Math.max(0, s - PAGE_SIZE))}
            >
              &lsaquo;
            </button>
            <span className="series-pagination-page-total">
              {currentPage} / {pageCount}
            </span>
            <button
              className="btn btn-small"
              type="button"
              disabled={currentPage >= pageCount}
              onClick={() => setSkip((s) => Math.min((pageCount - 1) * PAGE_SIZE, s + PAGE_SIZE))}
            >
              &rsaquo;
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
