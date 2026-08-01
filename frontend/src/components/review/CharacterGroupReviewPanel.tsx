import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type {
  CharacterGroupAction,
  CharacterGroupActionOp,
  CharacterGroupDetail,
  CharacterGroupMember,
  CharacterGroupReviewStatusFilter,
  CharacterGroupState,
  CharacterGroupStateFilter,
  CharacterGroupSummary,
  CharacterLinkCandidate,
} from "../../types";
import { catalogCoverImageUrl } from "../../utils/reviewImages";

const PAGE_SIZE = 20;

const STATE_LABELS: Record<CharacterGroupState, string> = {
  conflict: "충돌",
  pending: "대기",
  unlinked: "미연결",
  settled: "완료",
};

const STATE_FILTER_OPTIONS: Array<{ value: CharacterGroupStateFilter; label: string }> = [
  { value: "all", label: "전체 상태" },
  { value: "conflict", label: "충돌" },
  { value: "pending", label: "대기" },
  { value: "unlinked", label: "미연결" },
  { value: "settled", label: "완료" },
];

const REVIEW_STATUS_FILTER_OPTIONS: Array<{ value: CharacterGroupReviewStatusFilter; label: string }> = [
  { value: "all", label: "리뷰 상태 전체" },
  { value: "pending", label: "리뷰 대기" },
  { value: "completed", label: "리뷰 완료" },
];

const HAS_IMAGE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "이미지 전체" },
  { value: "true", label: "이미지 있음" },
  { value: "false", label: "이미지 없음" },
];

// 구조적 괄호 관계가 최우선이며 same_series는 단독 추천 근거로 표시하지 않는다.
// CharacterLinkModal의 라벨 정책과 동일하게 맞춘다.
const MATCH_REASON_LABELS: Record<string, string> = {
  structural_parent: "괄호 단계 축약 일치",
  structural_child: "괄호 단계 확장 일치",
  same_base: "기본 캐릭터명 일치",
  name_similarity: "이름 유사",
};

function matchReasonLabel(reason: string | null | undefined): string | null {
  if (!reason || reason === "same_series") {
    return null;
  }
  return MATCH_REASON_LABELS[reason] ?? null;
}

function candidateToMember(candidate: CharacterLinkCandidate): CharacterGroupMember {
  return {
    id: candidate.id,
    character_tag: candidate.character_tag,
    display_name: candidate.display_name,
    post_count: candidate.post_count,
    review_status: candidate.review_status,
    rating: candidate.rating,
    image_count: candidate.image_count,
    preview_image_path: candidate.cover_image_path,
    is_cover_preview: Boolean(candidate.cover_image_path),
  };
}

interface StagedAction {
  op: CharacterGroupActionOp;
  childId: number;
  newParentId?: number;
  newParentLabel?: string;
}

type ChildCardKind = "existing" | "suggested" | "manual";

interface ChildCardEntry {
  key: string;
  kind: ChildCardKind;
  member: CharacterGroupMember;
  score?: number;
  reason?: string | null;
}

interface CandidateSearchModalProps {
  title: string;
  description?: string;
  fetchCandidates: (search: string) => Promise<CharacterLinkCandidate[]>;
  onSelect: (candidate: CharacterLinkCandidate) => void;
  onClose: () => void;
}

function CandidateSearchModal({ title, description, fetchCandidates, onSelect, onClose }: CandidateSearchModalProps) {
  const [search, setSearch] = useState("");
  const [candidates, setCandidates] = useState<CharacterLinkCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const timer = window.setTimeout(
      () => {
        fetchCandidates(search)
          .then((items) => {
            if (cancelled) return;
            setCandidates(items);
          })
          .catch((err: unknown) => {
            if (cancelled) return;
            setError(err instanceof Error ? err.message : "후보를 불러오지 못했습니다.");
          })
          .finally(() => {
            if (!cancelled) setLoading(false);
          });
      },
      search ? 250 : 0,
    );
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [search, fetchCandidates]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [onClose]);

  return (
    <div className="modal-backdrop modal-backdrop-merge" onClick={onClose}>
      <div className="modal modal-wide modal-merge" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header-row">
          <div className="modal-header-copy">
            <h2 className="modal-title">{title}</h2>
            {description ? <p className="catalog-card-subtitle">{description}</p> : null}
          </div>
          <button className="btn btn-small" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <div className="modal-body-scroll">
          <div className="toolbar" style={{ marginBottom: 12 }}>
            <div className="field full-width">
              <label htmlFor="group-candidate-search">캐릭터 검색</label>
              <input
                id="group-candidate-search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="character tag / 이름 입력"
                autoComplete="off"
                autoFocus
              />
            </div>
          </div>
          {error ? <div className="error-banner">{error}</div> : null}
          {loading ? (
            <div className="empty-state">후보 불러오는 중...</div>
          ) : candidates.length === 0 ? (
            <div className="empty-state">검색 조건에 맞는 캐릭터가 없습니다.</div>
          ) : (
            <div className="merge-candidate-list" role="listbox" aria-label="character group candidates">
              {candidates.map((candidate) => (
                <button
                  key={candidate.id}
                  type="button"
                  role="option"
                  aria-selected={false}
                  className={`merge-candidate-item${!candidate.linkable ? " merge-candidate-item-disabled" : ""}`}
                  disabled={!candidate.linkable}
                  onClick={() => {
                    onSelect(candidate);
                    onClose();
                  }}
                >
                  <span className="merge-candidate-tag">{candidate.character_tag}</span>
                  {candidate.display_name ? (
                    <span className="merge-candidate-meta">{candidate.display_name}</span>
                  ) : null}
                  <span className="merge-candidate-stats">
                    posts {candidate.post_count.toLocaleString()}
                    {!candidate.linkable ? " · 연결 불가" : ""}
                    {candidate.similarity_score > 0
                      ? ` · match ${Math.round(candidate.similarity_score * 100)}%`
                      : ""}
                    {matchReasonLabel(candidate.match_reason)
                      ? ` · 추천 근거: ${matchReasonLabel(candidate.match_reason)}`
                      : ""}
                  </span>
                  {candidate.review_status === "completed" ? (
                    <span className="merge-candidate-badge merge-candidate-badge--completed">
                      완료{typeof candidate.rating === "number" ? ` ★${candidate.rating}` : ""}
                    </span>
                  ) : candidate.image_count > 0 ? (
                    <span className="merge-candidate-badge">생성됨 {candidate.image_count}장</span>
                  ) : null}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface ChildCardProps {
  entry: ChildCardEntry;
  staged?: StagedAction;
  onAccept: () => void;
  onReject: () => void;
  onUnlink: () => void;
  onMove: () => void;
  onUndo: () => void;
}

function ChildCard({ entry, staged, onAccept, onReject, onUnlink, onMove, onUndo }: ChildCardProps) {
  const { member } = entry;
  const imageUrl = catalogCoverImageUrl(member.preview_image_path, 320);
  const stagedLabel =
    staged?.op === "accept" || staged?.op === "add"
      ? "추가 대기"
      : staged?.op === "reject"
        ? "거부 대기"
        : staged?.op === "unlink"
          ? "연결 해제 대기"
          : staged?.op === "move"
            ? `이동 대기 → ${staged.newParentLabel ?? staged.newParentId}`
            : null;
  const kindLabel = entry.kind === "existing" ? "기존" : entry.kind === "suggested" ? "제안" : "수동 추가";
  const removalStaged = staged?.op === "reject" || staged?.op === "unlink";
  const cardStateClass = staged ? (removalStaged ? " character-group-card--pending-remove" : " character-group-card--pending-add") : "";

  return (
    <article className={`character-group-card character-group-card--${entry.kind}${cardStateClass}`}>
      <div className="character-group-card-image-wrap">
        {imageUrl ? (
          <img src={imageUrl} alt={member.character_tag} loading="lazy" />
        ) : (
          <div className="review-image-slot review-image-slot--empty">
            <span className="review-image-placeholder">No image</span>
          </div>
        )}
      </div>
      <div className="character-group-card-body">
        <div className="character-group-card-name-row">
          <span className={`badge character-group-card-kind character-group-card-kind--${entry.kind}`}>{kindLabel}</span>
          {stagedLabel ? <span className="badge badge-warning">{stagedLabel}</span> : null}
        </div>
        <h4 className="character-group-card-tag">{member.character_tag}</h4>
        {member.display_name ? <p className="catalog-card-subtitle">{member.display_name}</p> : null}
        <div className="character-group-card-meta">
          <span className="badge badge-muted">posts {member.post_count.toLocaleString()}</span>
          {member.review_status === "completed" ? (
            <span className="badge badge-success">
              완료{typeof member.rating === "number" ? ` ★${member.rating}` : ""}
            </span>
          ) : member.image_count > 0 ? (
            <span className="badge badge-muted">생성됨 {member.image_count}</span>
          ) : (
            <span className="badge badge-muted">미생성</span>
          )}
          {entry.kind === "suggested" && typeof entry.score === "number" ? (
            <span className="badge badge-muted">match {Math.round(entry.score * 100)}%</span>
          ) : null}
        </div>
        {entry.kind === "suggested" && matchReasonLabel(entry.reason) ? (
          <p className="character-group-card-reason">추천 근거: {matchReasonLabel(entry.reason)}</p>
        ) : null}
        <div className="character-group-card-actions">
          {staged ? (
            <button className="btn btn-small" type="button" onClick={onUndo}>
              되돌리기
            </button>
          ) : entry.kind === "suggested" ? (
            <>
              <button className="btn btn-small btn-primary" type="button" onClick={onAccept}>
                수락
              </button>
              <button className="btn btn-small" type="button" onClick={onReject}>
                거부
              </button>
            </>
          ) : entry.kind === "existing" ? (
            <>
              <button className="btn btn-small" type="button" onClick={onUnlink}>
                연결 해제
              </button>
              <button className="btn btn-small" type="button" onClick={onMove}>
                다른 부모로 이동
              </button>
            </>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export function CharacterGroupReviewPanel() {
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<CharacterGroupStateFilter>("all");
  const [reviewStatusFilter, setReviewStatusFilter] = useState<CharacterGroupReviewStatusFilter>("all");
  const [hasImageFilter, setHasImageFilter] = useState("");
  const [skip, setSkip] = useState(0);

  const [groups, setGroups] = useState<CharacterGroupSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedParentId, setSelectedParentId] = useState<number | null>(null);
  const [detail, setDetail] = useState<CharacterGroupDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [recalculating, setRecalculating] = useState(false);
  const [applying, setApplying] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const [stagedActions, setStagedActions] = useState<Record<number, StagedAction>>({});
  const [manualMembers, setManualMembers] = useState<CharacterGroupMember[]>([]);

  const [addChildModalOpen, setAddChildModalOpen] = useState(false);
  const [moveChildTarget, setMoveChildTarget] = useState<CharacterGroupMember | null>(null);

  const loadGroups = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      const response = await api.listCharacterGroups({
        search: search || undefined,
        state: stateFilter,
        has_image: hasImageFilter ? hasImageFilter === "true" : undefined,
        review_status: reviewStatusFilter,
        skip,
        limit: PAGE_SIZE,
      });
      setGroups(response.items);
      setTotal(response.total);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "그룹 목록을 불러오지 못했습니다.");
    } finally {
      setListLoading(false);
    }
  }, [search, stateFilter, hasImageFilter, reviewStatusFilter, skip]);

  useEffect(() => {
    void loadGroups();
  }, [loadGroups]);

  useEffect(() => {
    setSkip(0);
  }, [search, stateFilter, hasImageFilter, reviewStatusFilter]);

  const loadDetail = useCallback(async (parentId: number) => {
    setDetailLoading(true);
    setDetailError(null);
    try {
      const response = await api.getCharacterGroup(parentId);
      setDetail(response);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "그룹 상세 정보를 불러오지 못했습니다.");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedParentId == null) {
      setDetail(null);
      return;
    }
    setStagedActions({});
    setManualMembers([]);
    setActionMessage(null);
    void loadDetail(selectedParentId);
  }, [selectedParentId, loadDetail]);

  const entries: ChildCardEntry[] = useMemo(() => {
    if (!detail) {
      return [];
    }
    const list: ChildCardEntry[] = [];
    for (const child of detail.children) {
      list.push({ key: `existing-${child.id}`, kind: "existing", member: child });
    }
    for (const suggestion of detail.suggestions) {
      list.push({
        key: `suggested-${suggestion.child.id}`,
        kind: "suggested",
        member: suggestion.child,
        score: suggestion.score,
        reason: suggestion.reason,
      });
    }
    for (const member of manualMembers) {
      list.push({ key: `manual-${member.id}`, kind: "manual", member });
    }
    return list;
  }, [detail, manualMembers]);

  const parentImageUrl = useMemo(
    () => catalogCoverImageUrl(detail?.parent.preview_image_path ?? null, 480),
    [detail],
  );

  const stageAction = (childId: number, action: StagedAction) => {
    setStagedActions((current) => ({ ...current, [childId]: action }));
  };

  const undoAction = (childId: number) => {
    setStagedActions((current) => {
      if (!(childId in current)) {
        return current;
      }
      const next = { ...current };
      delete next[childId];
      return next;
    });
    setManualMembers((current) => current.filter((member) => member.id !== childId));
  };

  const handleAccept = (childId: number) => stageAction(childId, { op: "accept", childId });
  const handleReject = (childId: number) => stageAction(childId, { op: "reject", childId });
  const handleUnlink = (childId: number) => stageAction(childId, { op: "unlink", childId });

  const handleMoveSelected = (childId: number, candidate: CharacterLinkCandidate) => {
    stageAction(childId, {
      op: "move",
      childId,
      newParentId: candidate.id,
      newParentLabel: candidate.display_name || candidate.character_tag,
    });
  };

  const handleManualAdd = (candidate: CharacterLinkCandidate) => {
    const member = candidateToMember(candidate);
    setManualMembers((current) => (current.some((entry) => entry.id === member.id) ? current : [...current, member]));
    stageAction(member.id, { op: "add", childId: member.id });
  };

  const hasStagedActions = Object.keys(stagedActions).length > 0;

  const applyStaged = async () => {
    if (!detail || !hasStagedActions) {
      return;
    }
    setApplying(true);
    setDetailError(null);
    try {
      const actions: CharacterGroupAction[] = Object.values(stagedActions).map((action) => ({
        op: action.op,
        child_id: action.childId,
        new_parent_id: action.op === "move" ? action.newParentId ?? null : undefined,
      }));
      const response = await api.applyCharacterGroupActions(detail.parent.id, actions);
      setDetail(response);
      setStagedActions({});
      setManualMembers([]);
      setActionMessage(`${actions.length}건의 변경사항을 적용했습니다.`);
      void loadGroups();
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "변경사항 적용에 실패했습니다.");
    } finally {
      setApplying(false);
    }
  };

  const recalculate = async () => {
    if (!detail) {
      return;
    }
    if (hasStagedActions && !window.confirm("재계산하면 저장하지 않은 임시 편집 내용이 초기화됩니다. 계속할까요?")) {
      return;
    }
    setRecalculating(true);
    setDetailError(null);
    try {
      const response = await api.recalculateCharacterGroup(detail.parent.id);
      setDetail(response);
      setStagedActions({});
      setManualMembers([]);
      setActionMessage("추천을 다시 계산했습니다.");
      void loadGroups();
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "재계산에 실패했습니다.");
    } finally {
      setRecalculating(false);
    }
  };

  const fetchChildCandidates = useCallback(
    async (searchTerm: string) => {
      if (!detail) {
        return [];
      }
      const excludeIds = [
        detail.parent.id,
        ...detail.children.map((child) => child.id),
        ...detail.suggestions.map((suggestion) => suggestion.child.id),
        ...manualMembers.map((member) => member.id),
      ];
      const response = await api.listCharacterLinkCandidates(detail.parent.id, {
        mode: "child",
        search: searchTerm || undefined,
        exclude_ids: excludeIds,
        limit: searchTerm ? 100 : 50,
      });
      return response.items;
    },
    [detail, manualMembers],
  );

  const fetchParentCandidatesForMove = useCallback(
    async (searchTerm: string) => {
      if (!moveChildTarget) {
        return [];
      }
      const response = await api.listCharacterLinkCandidates(moveChildTarget.id, {
        mode: "parent",
        search: searchTerm || undefined,
        exclude_ids: detail ? [detail.parent.id] : undefined,
        limit: searchTerm ? 100 : 50,
      });
      return response.items;
    },
    [moveChildTarget, detail],
  );

  const pageStart = groups.length > 0 ? skip + 1 : 0;
  const pageEnd = skip + groups.length;

  return (
    <div className="character-group-review">
      <div className="toolbar character-group-toolbar">
        <div className="field">
          <label htmlFor="group-search">검색</label>
          <input
            id="group-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="character tag / 이름"
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="group-state-filter">상태</label>
          <select
            id="group-state-filter"
            value={stateFilter}
            onChange={(event) => setStateFilter(event.target.value as CharacterGroupStateFilter)}
          >
            {STATE_FILTER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="group-review-filter">리뷰 상태</label>
          <select
            id="group-review-filter"
            value={reviewStatusFilter}
            onChange={(event) => setReviewStatusFilter(event.target.value as CharacterGroupReviewStatusFilter)}
          >
            {REVIEW_STATUS_FILTER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="group-image-filter">이미지</label>
          <select id="group-image-filter" value={hasImageFilter} onChange={(event) => setHasImageFilter(event.target.value)}>
            {HAS_IMAGE_OPTIONS.map((option) => (
              <option key={option.value || "all"} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {listError ? <div className="error-banner">{listError}</div> : null}
      {actionMessage ? <p className="catalog-card-subtitle character-group-action-message">{actionMessage}</p> : null}

      <div className="character-group-list-panel">
        {listLoading ? (
          <div className="empty-state">그룹 목록 불러오는 중...</div>
        ) : groups.length === 0 ? (
          <div className="empty-state">조건에 맞는 그룹이 없습니다.</div>
        ) : (
          <div className="character-group-list" role="list" aria-label="parent/child review groups">
            {groups.map((group) => {
              const isSelected = group.parent.id === selectedParentId;
              return (
                <button
                  key={group.parent.id}
                  type="button"
                  role="listitem"
                  aria-current={isSelected}
                  className={`character-group-list-item${isSelected ? " character-group-list-item--selected" : ""}`}
                  onClick={() => setSelectedParentId(group.parent.id)}
                >
                  <span className={`badge character-group-state-badge character-group-state-badge--${group.state}`}>
                    {STATE_LABELS[group.state]}
                  </span>
                  <span className="character-group-list-tag">{group.parent.character_tag}</span>
                  {group.parent.display_name ? (
                    <span className="character-group-list-name">{group.parent.display_name}</span>
                  ) : null}
                  <span className="badge badge-muted">자식 {group.child_count}</span>
                  {group.pending_count > 0 ? <span className="badge badge-warning">대기 {group.pending_count}</span> : null}
                </button>
              );
            })}
          </div>
        )}
        <div className="series-pagination-controls" aria-label="character group pagination">
          <button className="btn btn-small" type="button" disabled={skip === 0} onClick={() => setSkip(0)}>
            &laquo;
          </button>
          <button
            className="btn btn-small"
            type="button"
            disabled={skip === 0}
            onClick={() => setSkip((value) => Math.max(0, value - PAGE_SIZE))}
          >
            &lsaquo;
          </button>
          <span className="series-pagination-page-total">
            {pageStart}-{pageEnd} / {total}
          </span>
          <button
            className="btn btn-small"
            type="button"
            disabled={pageEnd >= total}
            onClick={() => setSkip((value) => value + PAGE_SIZE)}
          >
            &rsaquo;
          </button>
        </div>
      </div>

      <div className="character-group-detail">
        {selectedParentId == null ? (
          <div className="empty-state">왼쪽 목록에서 그룹을 선택하세요.</div>
        ) : detailLoading ? (
          <div className="empty-state">그룹 상세 불러오는 중...</div>
        ) : detailError ? (
          <div className="error-banner">{detailError}</div>
        ) : detail ? (
          <>
            <div className="character-group-detail-header">
              <span className={`badge character-group-state-badge character-group-state-badge--${detail.state}`}>
                {STATE_LABELS[detail.state]}
              </span>
              {detail.state === "conflict" ? (
                <span className="badge badge-danger">동일 자식이 여러 부모에 동시에 제안됨 - 신중히 확인하세요</span>
              ) : null}
              <div className="character-group-detail-actions">
                <button className="btn btn-small" type="button" disabled={recalculating} onClick={() => void recalculate()}>
                  {recalculating ? "재계산 중..." : "추천 재계산"}
                </button>
                <button className="btn btn-small" type="button" onClick={() => setAddChildModalOpen(true)}>
                  자식 수동 추가
                </button>
                <button
                  className="btn btn-small btn-primary"
                  type="button"
                  disabled={!hasStagedActions || applying}
                  onClick={() => void applyStaged()}
                >
                  {applying ? "적용 중..." : `변경사항 적용 (${Object.keys(stagedActions).length})`}
                </button>
              </div>
            </div>

            <div className="character-group-detail-body">
              <div className="character-group-parent-card">
                <div className="character-group-card-image-wrap character-group-parent-image">
                  {parentImageUrl ? (
                    <img src={parentImageUrl} alt={detail.parent.character_tag} />
                  ) : (
                    <div className="review-image-slot review-image-slot--empty">
                      <span className="review-image-placeholder">No image</span>
                    </div>
                  )}
                </div>
                <h3 className="character-group-card-tag">{detail.parent.character_tag}</h3>
                {detail.parent.display_name ? <p className="catalog-card-subtitle">{detail.parent.display_name}</p> : null}
                <div className="character-group-card-meta">
                  <span className="badge badge-muted">posts {detail.parent.post_count.toLocaleString()}</span>
                  {detail.parent.review_status === "completed" ? (
                    <span className="badge badge-success">
                      완료{typeof detail.parent.rating === "number" ? ` ★${detail.parent.rating}` : ""}
                    </span>
                  ) : (
                    <span className="badge badge-muted">리뷰 대기</span>
                  )}
                  <span className="badge badge-muted">자식 {detail.children.length}</span>
                </div>
              </div>

              <div className="character-group-children-grid">
                {entries.length === 0 ? (
                  <div className="empty-state">기존 자식 또는 제안된 후보가 없습니다.</div>
                ) : (
                  entries.map((entry) => (
                    <ChildCard
                      key={entry.key}
                      entry={entry}
                      staged={stagedActions[entry.member.id]}
                      onAccept={() => handleAccept(entry.member.id)}
                      onReject={() => handleReject(entry.member.id)}
                      onUnlink={() => handleUnlink(entry.member.id)}
                      onMove={() => setMoveChildTarget(entry.member)}
                      onUndo={() => undoAction(entry.member.id)}
                    />
                  ))
                )}
              </div>
            </div>
          </>
        ) : null}
      </div>

      {addChildModalOpen && detail ? (
        <CandidateSearchModal
          title={`${detail.parent.character_tag} 하위(Alternative) 캐릭터 수동 추가`}
          description="검색 후 선택하면 변경사항 적용 전까지 임시로 추가됩니다."
          fetchCandidates={fetchChildCandidates}
          onSelect={handleManualAdd}
          onClose={() => setAddChildModalOpen(false)}
        />
      ) : null}

      {moveChildTarget ? (
        <CandidateSearchModal
          title={`${moveChildTarget.character_tag} 새 부모로 이동`}
          description="선택하면 변경사항 적용 전까지 임시로 이동 대기 상태가 됩니다."
          fetchCandidates={fetchParentCandidatesForMove}
          onSelect={(candidate) => {
            handleMoveSelected(moveChildTarget.id, candidate);
            setMoveChildTarget(null);
          }}
          onClose={() => setMoveChildTarget(null)}
        />
      ) : null}
    </div>
  );
}
