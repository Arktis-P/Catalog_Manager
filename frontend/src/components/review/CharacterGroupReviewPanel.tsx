import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
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
import { cycleGender, genderChipClass, genderChipLabel } from "../../utils/reviewPrompt";
import { danbooruPostsUrl, danbooruWikiUrl, openExternal } from "../../utils/danbooruLinks";
import { useGenerationJobs } from "../../context/GenerationJobContext";
import { ReviewRatingStars, toggleRating } from "./ReviewRatingStars";

const PAGE_SIZE_OPTIONS = [50, 100, 200, 300];

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

function memberTextLine(member: CharacterGroupMember): string {
  const parts = [member.character_tag];
  if (member.display_name) {
    parts.push(member.display_name);
  }
  parts.push(`posts ${member.post_count.toLocaleString()}`);
  if (member.review_status === "completed") {
    parts.push(`완료${typeof member.rating === "number" ? ` ★${member.rating}` : ""}`);
  } else if (member.image_count > 0) {
    parts.push(`생성됨 ${member.image_count}`);
  }
  return parts.join(" · ");
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
  stagedEdit?: { rating?: number | null; gender?: string | null };
  parentRating?: number | null;
  parentGender?: string | null;
  isCompleteStaged?: boolean;
  isRegenerating?: boolean;
  selected: boolean;
  onSelect: () => void;
  onAccept: () => void;
  onReject: () => void;
  onUnlink: () => void;
  onMove: () => void;
  onUndo: () => void;
  onRate: (rating: number) => void;
  onCycleGender: (currentGender: string | null | undefined) => void;
  onToggleComplete: () => void;
}

function resolveRating(member: CharacterGroupMember, parentRating?: number | null, stagedEdit?: { rating?: number | null }): number | null {
  if (stagedEdit?.rating !== undefined) {
    return stagedEdit.rating;
  }
  if (member.rating !== null && member.rating !== undefined) {
    return member.rating;
  }
  return parentRating ?? null;
}

function resolveGender(member: CharacterGroupMember, parentGender?: string | null, stagedEdit?: { gender?: string | null }): string | null {
  if (stagedEdit?.gender !== undefined) {
    return stagedEdit.gender;
  }
  if (member.gender !== null && member.gender !== undefined) {
    return member.gender;
  }
  return parentGender ?? null;
}

function ChildCard({
  entry,
  staged,
  stagedEdit,
  parentRating,
  parentGender,
  isCompleteStaged,
  isRegenerating,
  selected,
  onSelect,
  onAccept,
  onReject,
  onUnlink,
  onMove,
  onUndo,
  onRate,
  onCycleGender,
  onToggleComplete,
}: ChildCardProps) {
  const { member } = entry;
  const withStop = (handler: () => void) => (event: ReactMouseEvent) => {
    event.stopPropagation();
    handler();
  };
  const imageUrl = catalogCoverImageUrl(member.preview_image_path, 320);
  const effectiveRating = resolveRating(member, parentRating, stagedEdit);
  const effectiveGender = resolveGender(member, parentGender, stagedEdit);

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
    <article
      className={`character-group-card character-group-card--${entry.kind}${cardStateClass}${selected ? " character-group-card--selected" : ""}${isRegenerating ? " character-group-card--locked" : ""}`}
      data-child-card-key={entry.key}
      aria-current={selected || undefined}
      onClick={onSelect}
    >
      {isRegenerating ? (
        <div className="v2-review-card-regenerate-banner">
          <span>재생성 중...</span>
        </div>
      ) : null}
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
          {isCompleteStaged ? <span className="badge badge-success">완료 대기</span> : null}
        </div>
        <h4 className="character-group-card-tag">{member.character_tag}</h4>
        {member.display_name ? <p className="catalog-card-subtitle">{member.display_name}</p> : null}
        <div className="character-group-card-meta">
          <button
            type="button"
            className={genderChipClass(effectiveGender)}
            disabled={isRegenerating}
            onClick={withStop(() => onCycleGender(effectiveGender))}
          >
            {genderChipLabel(effectiveGender)}
          </button>
          <span className="badge badge-muted">posts {member.post_count.toLocaleString()}</span>
          {entry.kind === "suggested" && typeof entry.score === "number" ? (
            <span className="badge badge-muted">match {Math.round(entry.score * 100)}%</span>
          ) : null}
        </div>
        {entry.kind === "suggested" && matchReasonLabel(entry.reason) ? (
          <p className="character-group-card-reason">추천 근거: {matchReasonLabel(entry.reason)}</p>
        ) : null}
        <ReviewRatingStars rating={effectiveRating} onRate={onRate} />
        <div className="character-group-card-actions">
          {isCompleteStaged ? (
            <button className="btn btn-small btn-success" type="button" disabled={isRegenerating} onClick={withStop(onToggleComplete)}>
              완료대기 (취소)
            </button>
          ) : staged ? (
            <>
              <button className="btn btn-small" type="button" disabled={isRegenerating} onClick={withStop(onUndo)}>
                되돌리기
              </button>
              {(staged.op === "accept" || staged.op === "add") && (
                <button className="btn btn-small" type="button" disabled={isRegenerating} onClick={withStop(onToggleComplete)}>
                  완료대기
                </button>
              )}
            </>
          ) : entry.kind === "suggested" ? (
            <>
              <button className="btn btn-small btn-primary" type="button" disabled={isRegenerating} onClick={withStop(onAccept)}>
                수락
              </button>
              <button className="btn btn-small" type="button" disabled={isRegenerating} onClick={withStop(onReject)}>
                거부
              </button>
            </>
          ) : entry.kind === "existing" ? (
            <>
              <button className="btn btn-small" type="button" disabled={isRegenerating} onClick={withStop(onUnlink)}>
                연결 해제
              </button>
              <button className="btn btn-small" type="button" disabled={isRegenerating} onClick={withStop(onMove)}>
                다른 부모로 이동
              </button>
              <button className="btn btn-small" type="button" disabled={isRegenerating} onClick={withStop(onToggleComplete)}>
                완료대기
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
  const [pageSize, setPageSize] = useState(50);
  const [skip, setSkip] = useState(0);

  const [groups, setGroups] = useState<CharacterGroupSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  // The row a user last interacted with. Space (and the per-row detail button) opens
  // the full image-rich detail overlay for exactly this one parent.
  const [selectedParentId, setSelectedParentId] = useState<number | null>(null);
  const selectedRowRef = useRef<HTMLDivElement | null>(null);

  // Row-level text expansion is independent from the detail overlay: it fetches the
  // same read-only group detail but renders children/suggestions as plain text, with
  // no images and no staged-action controls. Collapsed by default; only one row's
  // text expands at a time.
  const [expandedParentId, setExpandedParentId] = useState<number | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<CharacterGroupDetail | null>(null);
  const [expandedLoading, setExpandedLoading] = useState(false);
  const [expandedError, setExpandedError] = useState<string | null>(null);

  // The image-rich/card detail view opens for at most one parent at a time.
  const [detailParentId, setDetailParentId] = useState<number | null>(null);
  const [detail, setDetail] = useState<CharacterGroupDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [recalculating, setRecalculating] = useState(false);
  const [applying, setApplying] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const { v2Jobs, startV2Regeneration } = useGenerationJobs();
  const processedV2JobIdsRef = useRef<Set<string>>(new Set());

  const [stagedActions, setStagedActions] = useState<Record<number, StagedAction>>({});
  const [stagedMemberEdits, setStagedMemberEdits] = useState<Record<number, { rating?: number | null; gender?: string | null }>>({});
  const [stagedCompletes, setStagedCompletes] = useState<Set<number>>(new Set());
  const [manualMembers, setManualMembers] = useState<CharacterGroupMember[]>([]);

  const isCharacterRegenerating = useCallback(
    (characterId: number) => {
      const job = v2Jobs.find((j) => j.kind === "regenerate" && j.character_id === characterId);
      return Boolean(job && (job.status === "queued" || job.status === "running" || job.status === "paused"));
    },
    [v2Jobs],
  );

  const [addChildModalOpen, setAddChildModalOpen] = useState(false);
  const [moveChildTarget, setMoveChildTarget] = useState<CharacterGroupMember | null>(null);
  const [selectedChildKey, setSelectedChildKey] = useState<string | null>(null);
  const childrenGridRef = useRef<HTMLDivElement>(null);
  const [childGridColumns, setChildGridColumns] = useState(4);

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
        limit: pageSize,
      });
      setGroups(response.items);
      setTotal(response.total);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "그룹 목록을 불러오지 못했습니다.");
    } finally {
      setListLoading(false);
    }
  }, [search, stateFilter, hasImageFilter, reviewStatusFilter, skip, pageSize]);

  useEffect(() => {
    void loadGroups();
  }, [loadGroups]);

  useEffect(() => {
    setSkip(0);
  }, [search, stateFilter, hasImageFilter, reviewStatusFilter, pageSize]);

  useEffect(() => {
    if (groups.length > 0) {
      if (selectedParentId == null || !groups.some((g) => g.parent.id === selectedParentId)) {
        setSelectedParentId(groups[0].parent.id);
      }
    } else {
      setSelectedParentId(null);
    }
  }, [groups]);

  useEffect(() => {
    if (selectedParentId != null && selectedRowRef.current) {
      selectedRowRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [selectedParentId]);

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
    if (detailParentId == null) {
      setDetail(null);
      return;
    }
    setStagedActions({});
    setStagedMemberEdits({});
    setStagedCompletes(new Set());
    setManualMembers([]);
    setSelectedChildKey(null);
    setActionMessage(null);
    void loadDetail(detailParentId);
  }, [detailParentId, loadDetail]);

  useEffect(() => {
    if (!detail) return;
    for (const job of v2Jobs) {
      if (job.kind === "regenerate" && !processedV2JobIdsRef.current.has(job.job_id)) {
        if (job.status === "completed" || job.status === "failed") {
          processedV2JobIdsRef.current.add(job.job_id);
          if (job.status === "completed") {
            setActionMessage(`${job.current_character_tag ?? "캐릭터"} 이미지 재생성 완료`);
            void loadDetail(detail.parent.id);
            void loadGroups();
          } else if (job.status === "failed") {
            setActionMessage(`${job.current_character_tag ?? "캐릭터"} 재생성 실패: ${job.last_failure_reason || job.message || ""}`);
          }
        }
      }
    }
  }, [v2Jobs, detail, loadDetail, loadGroups]);

  const loadExpanded = useCallback(async (parentId: number) => {
    setExpandedLoading(true);
    setExpandedError(null);
    try {
      const response = await api.getCharacterGroup(parentId);
      setExpandedDetail(response);
    } catch (err) {
      setExpandedError(err instanceof Error ? err.message : "그룹 정보를 불러오지 못했습니다.");
    } finally {
      setExpandedLoading(false);
    }
  }, []);

  useEffect(() => {
    if (expandedParentId == null) {
      setExpandedDetail(null);
      setExpandedError(null);
      return;
    }
    void loadExpanded(expandedParentId);
  }, [expandedParentId, loadExpanded]);

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

  useEffect(() => {
    if (!entries.length) {
      setSelectedChildKey(null);
      return;
    }
    setSelectedChildKey((current) => {
      if (current && entries.some((entry) => entry.key === current)) return current;
      return entries[0].key;
    });
  }, [entries]);

  useEffect(() => {
    if (!selectedChildKey) return;
    childrenGridRef.current?.querySelector(`[data-child-card-key="${selectedChildKey}"]`)?.scrollIntoView({ block: "nearest" });
  }, [selectedChildKey]);

  useEffect(() => {
    const grid = childrenGridRef.current;
    if (!grid) return;
    const measure = () => {
      const columns = window.getComputedStyle(grid).gridTemplateColumns.split(" ").filter(Boolean).length;
      setChildGridColumns(Math.max(1, columns));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    return () => observer.disconnect();
  }, [entries.length]);

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
    setStagedCompletes((current) => {
      if (!current.has(childId)) return current;
      const next = new Set(current);
      next.delete(childId);
      return next;
    });
    setManualMembers((current) => current.filter((member) => member.id !== childId));
  };

  const handleAccept = (childId: number) => {
    stageAction(childId, { op: "accept", childId });
    if (detail) {
      const parentStaged = stagedMemberEdits[detail.parent.id];
      const parentEffectiveRating = resolveRating(detail.parent, null, parentStaged);
      const childMember = entries.find((e) => e.member.id === childId)?.member;
      if (childMember && childMember.rating == null && parentEffectiveRating != null && stagedMemberEdits[childId]?.rating === undefined) {
        stageRating(childId, parentEffectiveRating);
      }
    }
  };

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
    if (detail) {
      const parentStaged = stagedMemberEdits[detail.parent.id];
      const parentEffectiveRating = resolveRating(detail.parent, null, parentStaged);
      if (member.rating == null && parentEffectiveRating != null && stagedMemberEdits[member.id]?.rating === undefined) {
        stageRating(member.id, parentEffectiveRating);
      }
    }
  };

  const stageRating = (memberId: number, rating: number) => {
    setStagedMemberEdits((current) => {
      const existingEdit = current[memberId];
      const childEntry = entries.find((e) => e.member.id === memberId);
      const isStagedAccept = stagedActions[memberId]?.op === "accept" || stagedActions[memberId]?.op === "add";
      const parentStaged = current[detail?.parent.id ?? -1];
      const parentEffectiveRating = detail ? resolveRating(detail.parent, null, parentStaged) : null;

      const currentRating = existingEdit?.rating !== undefined
        ? existingEdit.rating
        : (detail?.parent.id === memberId
            ? detail.parent.rating
            : (childEntry
                ? (childEntry.kind === "suggested" && !isStagedAccept
                    ? resolveRating(childEntry.member, null)
                    : resolveRating(childEntry.member, parentEffectiveRating))
                : null));

      const nextRating = toggleRating(currentRating ?? null, rating);
      return {
        ...current,
        [memberId]: {
          ...current[memberId],
          rating: nextRating,
        },
      };
    });

    setStagedCompletes((current) => {
      if (!current.has(memberId)) return current;
      const memberObj = detail?.parent.id === memberId ? detail.parent : entries.find((e) => e.member.id === memberId)?.member;
      if (!memberObj) return current;

      const existingEdit = stagedMemberEdits[memberId];
      const childEntry = entries.find((e) => e.member.id === memberId);
      const isStagedAccept = stagedActions[memberId]?.op === "accept" || stagedActions[memberId]?.op === "add";
      const parentStaged = stagedMemberEdits[detail?.parent.id ?? -1];
      const parentEffectiveRating = detail ? resolveRating(detail.parent, null, parentStaged) : null;
      const currentRating = existingEdit?.rating !== undefined
        ? existingEdit.rating
        : (detail?.parent.id === memberId
            ? detail.parent.rating
            : (childEntry
                ? (childEntry.kind === "suggested" && !isStagedAccept
                    ? resolveRating(childEntry.member, null)
                    : resolveRating(childEntry.member, parentEffectiveRating))
                : null));
      const nextRating = toggleRating(currentRating ?? null, rating);

      if (!canStageComplete(memberObj, nextRating)) {
        const next = new Set(current);
        next.delete(memberId);
        return next;
      }
      return current;
    });
  };

  const stageGender = (memberId: number, currentGender: string | null | undefined) => {
    const nextGender = cycleGender(currentGender);
    setStagedMemberEdits((current) => ({
      ...current,
      [memberId]: {
        ...current[memberId],
        gender: nextGender,
      },
    }));
  };

  const canStageComplete = (member: CharacterGroupMember, effectiveRating: number | null): boolean => {
    if (effectiveRating === null || effectiveRating === undefined) {
      return false;
    }
    if (member.image_count > 0) {
      return true;
    }
    return effectiveRating === 0 || effectiveRating === -1;
  };

  const toggleStageComplete = (memberId: number, member: CharacterGroupMember, effectiveRating: number | null) => {
    if (stagedCompletes.has(memberId)) {
      setStagedCompletes((current) => {
        const next = new Set(current);
        next.delete(memberId);
        return next;
      });
      return;
    }
    if (!canStageComplete(member, effectiveRating)) {
      if (effectiveRating === null) {
        setActionMessage("별점 정보가 없으면 완료대기로 전환할 수 없습니다.");
      } else if (member.image_count === 0 && effectiveRating !== 0 && effectiveRating !== -1) {
        setActionMessage("이미지가 없는 항목은 0성 또는 -1성 별점일 때만 완료대기가 가능합니다.");
      } else {
        setActionMessage("완료대기 전환 조건에 맞지 않습니다.");
      }
      return;
    }
    setStagedCompletes((current) => new Set(current).add(memberId));
  };

  const hasStagedActions =
    Object.keys(stagedActions).length > 0 ||
    Object.keys(stagedMemberEdits).length > 0 ||
    stagedCompletes.size > 0;
  const stagedCount =
    Object.keys(stagedActions).length +
    Object.keys(stagedMemberEdits).length +
    stagedCompletes.size;

  const applyStaged = async () => {
    if (!detail || !hasStagedActions) {
      return;
    }
    setApplying(true);
    setDetailError(null);
    try {
      if (Object.keys(stagedActions).length > 0) {
        const actions: CharacterGroupAction[] = Object.values(stagedActions).map((action) => ({
          op: action.op,
          child_id: action.childId,
          new_parent_id: action.op === "move" ? action.newParentId ?? null : undefined,
        }));
        await api.applyCharacterGroupActions(detail.parent.id, actions);
      }

      const parentEffectiveRating = resolveRating(detail.parent, null, stagedMemberEdits[detail.parent.id]);
      const parentEffectiveGender = resolveGender(detail.parent, null, stagedMemberEdits[detail.parent.id]);

      const savesToPerform = new Map<number, { rating?: number | null; gender?: string | null }>();

      for (const [idStr, edit] of Object.entries(stagedMemberEdits)) {
        savesToPerform.set(Number(idStr), edit);
      }

      for (const staged of Object.values(stagedActions)) {
        if (staged.op === "accept" || staged.op === "add") {
          const childId = staged.childId;
          if (!savesToPerform.has(childId)) {
            const childMember = entries.find((e) => e.member.id === childId)?.member;
            if (childMember) {
              const r = resolveRating(childMember, parentEffectiveRating);
              const g = resolveGender(childMember, parentEffectiveGender);
              savesToPerform.set(childId, { rating: r, gender: g });
            }
          }
        }
      }

      // 1) Complete items in stagedCompletes via api.completeV2ReviewCharacter
      for (const memberId of stagedCompletes) {
        const edit = savesToPerform.get(memberId) ?? {};
        await api.completeV2ReviewCharacter(memberId, {
          rating: edit.rating ?? null,
          gender: edit.gender ?? null,
          cover_image_id: null,
          base_prompt: null,
          selected_tags: null,
        });
        savesToPerform.delete(memberId);
      }

      // 2) Save remaining staged attribute edits via api.saveV2ReviewCharacter
      for (const [memberId, edit] of savesToPerform.entries()) {
        await api.saveV2ReviewCharacter(memberId, {
          rating: edit.rating,
          gender: edit.gender,
        });
      }

      const response = await api.getCharacterGroup(detail.parent.id);
      setDetail(response);
      setStagedActions({});
      setStagedMemberEdits({});
      setStagedCompletes(new Set());
      setManualMembers([]);
      setActionMessage("변경사항을 적용했습니다.");
      void loadGroups();
      if (expandedParentId === detail.parent.id) {
        void loadExpanded(detail.parent.id);
      }
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "변경사항 적용에 실패했습니다.");
    } finally {
      setApplying(false);
    }
  };

  const recalculateParent = async (parentId: number) => {
    if (detailParentId === parentId && hasStagedActions && !window.confirm("재계산하면 저장하지 않은 임시 편집 내용이 초기화됩니다. 계속할까요?")) {
      return;
    }
    setRecalculating(true);
    setDetailError(null);
    try {
      const response = await api.recalculateCharacterGroup(parentId);
      if (detailParentId === parentId) {
        setDetail(response);
        setStagedActions({});
        setManualMembers([]);
      }
      setActionMessage("추천을 다시 계산했습니다.");
      void loadGroups();
      if (expandedParentId === parentId) {
        void loadExpanded(parentId);
      }
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "재계산에 실패했습니다.");
    } finally {
      setRecalculating(false);
    }
  };

  const recalculate = async () => {
    if (detail) {
      await recalculateParent(detail.parent.id);
    } else if (selectedParentId != null) {
      await recalculateParent(selectedParentId);
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

  const toggleExpand = useCallback((parentId: number) => {
    setExpandedParentId((current) => (current === parentId ? null : parentId));
  }, []);

  const openDetail = useCallback((parentId: number) => {
    setSelectedParentId(parentId);
    setDetailParentId(parentId);
  }, []);

  const closeDetail = useCallback(() => {
    setDetailParentId(null);
  }, []);

  const openAddChildForParent = useCallback((parentId: number) => {
    openDetail(parentId);
    setAddChildModalOpen(true);
  }, [openDetail]);

  useEffect(() => {
    const modalOpen = addChildModalOpen || moveChildTarget != null;
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        event.repeat ||
        target?.matches("input, textarea, select, [contenteditable=true]") ||
        target?.closest("[contenteditable=true]")
      ) {
        return;
      }

      if (modalOpen) {
        return;
      }

      const key = event.key.toLowerCase();

      // --- Detail Modal Open State ---
      if (detailParentId != null) {
        if (event.key === "Escape" && detail) {
          event.preventDefault();
          closeDetail();
          return;
        }

        // Ctrl + Left / Right in Detail Modal -> Navigate to Previous / Next item in group list
        if (event.ctrlKey && !event.altKey && !event.metaKey && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
          event.preventDefault();
          const currentIndex = groups.findIndex((g) => g.parent.id === detailParentId);
          if (event.key === "ArrowLeft" && currentIndex > 0) {
            openDetail(groups[currentIndex - 1].parent.id);
          } else if (event.key === "ArrowRight" && currentIndex >= 0 && currentIndex < groups.length - 1) {
            openDetail(groups[currentIndex + 1].parent.id);
          }
          return;
        }

        const selected = entries.find((entry) => entry.key === selectedChildKey);
        const selectedMember = selected?.member;

        if (event.ctrlKey && !event.altKey && !event.metaKey && event.key === "Enter") {
          if (hasStagedActions && !applying) {
            event.preventDefault();
            void applyStaged();
          }
          return;
        }
        if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key === "Enter") {
          if (selected) {
            if (selected.kind === "suggested" && !stagedActions[selected.member.id]) {
              event.preventDefault();
              handleAccept(selected.member.id);
              return;
            }
            if (detail) {
              event.preventDefault();
              const parentStaged = stagedMemberEdits[detail.parent.id];
              const parentEffectiveRating = resolveRating(detail.parent, null, parentStaged);
              const childStaged = stagedMemberEdits[selected.member.id];
              const effectiveRating = selected.kind === "suggested" && !stagedActions[selected.member.id]
                ? resolveRating(selected.member, null, childStaged)
                : resolveRating(selected.member, parentEffectiveRating, childStaged);
              toggleStageComplete(selected.member.id, selected.member, effectiveRating);
              return;
            }
          }
        }

        if (selectedMember && !event.ctrlKey && !event.metaKey && !event.altKey) {
          if (event.key >= "0" && event.key <= "6") {
            event.preventDefault();
            stageRating(selectedMember.id, Number(event.key));
            return;
          }
          if (key === "z") {
            event.preventDefault();
            stageRating(selectedMember.id, 0);
            return;
          }
          if (event.key === "-" || key === "x") {
            event.preventDefault();
            stageRating(selectedMember.id, -1);
            return;
          }
          if (key === "g" && detail) {
            event.preventDefault();
            const parentStaged = stagedMemberEdits[detail.parent.id];
            const parentEffectiveGender = resolveGender(detail.parent, null, parentStaged);
            const childStaged = stagedMemberEdits[selectedMember.id];
            const effectiveGender = resolveGender(selectedMember, parentEffectiveGender, childStaged);
            stageGender(selectedMember.id, effectiveGender);
            return;
          }
          if (key === "q" && detail) {
            event.preventDefault();
            openExternal(danbooruPostsUrl(selectedMember.character_tag, detail.parent.character_tag));
            return;
          }
          if (key === "w") {
            event.preventDefault();
            openExternal(danbooruWikiUrl(selectedMember.character_tag));
            return;
          }
          if (key === "r") {
            event.preventDefault();
            void startV2Regeneration(selectedMember.id, {})
              .then(() => setActionMessage(`${selectedMember.character_tag} V2 이미지 재생성을 시작했습니다.`))
              .catch((err: unknown) => setActionMessage(err instanceof Error ? err.message : "재생성에 실패했습니다."));
            return;
          }
        }

        if (!event.ctrlKey && !event.metaKey && !event.altKey && key === "a" && detail) {
          event.preventDefault();
          setAddChildModalOpen(true);
          return;
        }
        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key) && entries.length > 0) {
          event.preventDefault();
          const currentIndex = Math.max(0, entries.findIndex((entry) => entry.key === selectedChildKey));
          const delta = event.key === "ArrowLeft" ? -1 : event.key === "ArrowRight" ? 1 : event.key === "ArrowUp" ? -childGridColumns : childGridColumns;
          const nextIndex = Math.max(0, Math.min(entries.length - 1, currentIndex + delta));
          setSelectedChildKey(entries[nextIndex].key);
        }
        return;
      }

      // --- Detail Modal Closed State (Main List Navigation) ---
      if ((event.key === " " || event.code === "Space") && selectedParentId != null) {
        event.preventDefault();
        openDetail(selectedParentId);
        return;
      }

      if (!event.ctrlKey && !event.metaKey && !event.altKey && key === "r" && selectedParentId != null && !recalculating) {
        event.preventDefault();
        void recalculateParent(selectedParentId);
        return;
      }

      if (!event.ctrlKey && !event.metaKey && !event.altKey && key === "a" && selectedParentId != null) {
        event.preventDefault();
        openAddChildForParent(selectedParentId);
        return;
      }

      if (!event.ctrlKey && !event.metaKey && !event.altKey && groups.length > 0) {
        if (event.key === "ArrowUp") {
          event.preventDefault();
          const currentIndex = groups.findIndex((g) => g.parent.id === selectedParentId);
          if (currentIndex > 0) {
            setSelectedParentId(groups[currentIndex - 1].parent.id);
          } else if (currentIndex < 0) {
            setSelectedParentId(groups[0].parent.id);
          }
          return;
        }
        if (event.key === "ArrowDown") {
          event.preventDefault();
          const currentIndex = groups.findIndex((g) => g.parent.id === selectedParentId);
          if (currentIndex >= 0 && currentIndex < groups.length - 1) {
            setSelectedParentId(groups[currentIndex + 1].parent.id);
          } else if (currentIndex < 0) {
            setSelectedParentId(groups[0].parent.id);
          }
          return;
        }
        if (event.key === "ArrowRight" && selectedParentId != null) {
          event.preventDefault();
          setExpandedParentId(selectedParentId);
          return;
        }
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          setExpandedParentId(null);
          return;
        }
      }
    };
    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [
    addChildModalOpen,
    moveChildTarget,
    detailParentId,
    selectedParentId,
    detail,
    entries,
    selectedChildKey,
    childGridColumns,
    hasStagedActions,
    applying,
    stagedActions,
    recalculating,
    groups,
    openDetail,
    closeDetail,
    openAddChildForParent,
    handleAccept,
    applyStaged,
  ]);

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
        <div className="field">
          <label htmlFor="group-page-size">표시 개수</label>
          <select
            id="group-page-size"
            value={pageSize}
            onChange={(event) => setPageSize(Number(event.target.value))}
          >
            {PAGE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>
                {size}개씩 보기
              </option>
            ))}
          </select>
        </div>
      </div>

      <details className="review-shortcut-guide">
        <summary className="review-shortcut-guide-summary">
          단축키: ↑↓ 선택 이동 · ←→ 접기/펼치기 · Space 상세보기 · R 재계산 · A 자식 추가 · (상세 팝업 내) Ctrl+←→ 이전/다음 · Enter 수락 · Ctrl+Enter 적용
        </summary>
      </details>

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
              const isExpanded = group.parent.id === expandedParentId;
              return (
                <div
                  key={group.parent.id}
                  ref={isSelected ? selectedRowRef : undefined}
                  className="character-group-list-row"
                >
                  <div
                    role="listitem"
                    tabIndex={0}
                    aria-current={isSelected || undefined}
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
                    <div className="character-group-row-controls">
                      <button
                        className="btn btn-small"
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setSelectedParentId(group.parent.id);
                          toggleExpand(group.parent.id);
                        }}
                      >
                        {isExpanded ? "접기" : "펼치기"}
                      </button>
                      {isSelected ? (
                        <>
                          <button
                            className="btn btn-small"
                            type="button"
                            disabled={recalculating}
                            onClick={(event) => {
                              event.stopPropagation();
                              void recalculateParent(group.parent.id);
                            }}
                          >
                            추천 재계산
                          </button>
                          <button
                            className="btn btn-small"
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              openAddChildForParent(group.parent.id);
                            }}
                          >
                            자식 수동 추가
                          </button>
                        </>
                      ) : null}
                      <button
                        className="btn btn-small btn-primary"
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          openDetail(group.parent.id);
                        }}
                      >
                        상세보기 (Space)
                      </button>
                    </div>
                  </div>
                  {isExpanded ? (
                    <div className="character-group-row-expanded">
                      {expandedLoading ? (
                        <p className="empty-state">불러오는 중...</p>
                      ) : expandedError ? (
                        <p className="error-banner">{expandedError}</p>
                      ) : expandedDetail ? (
                        <>
                          <div className="character-group-row-expanded-section">
                            <h4>기존 자식 ({expandedDetail.children.length})</h4>
                            {expandedDetail.children.length === 0 ? (
                              <p className="catalog-card-subtitle">없음</p>
                            ) : (
                              <ul className="character-group-row-expanded-list">
                                {expandedDetail.children.map((child) => (
                                  <li key={child.id}>{memberTextLine(child)}</li>
                                ))}
                              </ul>
                            )}
                          </div>
                          <div className="character-group-row-expanded-section">
                            <h4>저장된 제안 ({expandedDetail.suggestions.length})</h4>
                            {expandedDetail.suggestions.length === 0 ? (
                              <p className="catalog-card-subtitle">없음</p>
                            ) : (
                              <ul className="character-group-row-expanded-list">
                                {expandedDetail.suggestions.map((suggestion) => (
                                  <li key={suggestion.child.id}>
                                    {memberTextLine(suggestion.child)}
                                    {` · match ${Math.round(suggestion.score * 100)}%`}
                                    {matchReasonLabel(suggestion.reason)
                                      ? ` · 추천 근거: ${matchReasonLabel(suggestion.reason)}`
                                      : ""}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        </>
                      ) : null}
                    </div>
                  ) : null}
                </div>
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
            onClick={() => setSkip((value) => Math.max(0, value - pageSize))}
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
            onClick={() => setSkip((value) => value + pageSize)}
          >
            &rsaquo;
          </button>
          <button className="btn btn-small" type="button" disabled={pageEnd >= total} onClick={() => setSkip(Math.max(0, (Math.ceil(total / pageSize) - 1) * pageSize))}>
            &raquo;
          </button>
        </div>
      </div>

      {detailParentId != null ? (
        <div className="modal-backdrop modal-backdrop-merge" onClick={closeDetail}>
          <div className="modal modal-wide" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header-row">
              <div className="modal-header-copy">
                <h2 className="modal-title">{detail ? detail.parent.character_tag : "상세보기"}</h2>
                {detail?.parent.display_name ? <p className="catalog-card-subtitle">{detail.parent.display_name}</p> : null}
              </div>
              <button className="btn btn-small" type="button" onClick={closeDetail}>
                Close
              </button>
            </div>
            <div className="modal-body-scroll">
              {detailLoading ? (
                <div className="empty-state">그룹 상세 불러오는 중...</div>
              ) : detailError ? (
                <div className="error-banner">{detailError}</div>
              ) : detail ? (
                <div className="character-group-detail">
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
                        {applying ? "적용 중..." : `변경사항 적용 (${stagedCount})`}
                      </button>
                    </div>
                  </div>

                  <div className="character-group-detail-body">
                    {(() => {
                      const parentStaged = stagedMemberEdits[detail.parent.id];
                      const parentEffectiveRating = resolveRating(detail.parent, null, parentStaged);
                      const parentEffectiveGender = resolveGender(detail.parent, null, parentStaged);

                      return (
                        <>
                          <div className="character-group-parent-card">
                            <div className="character-group-card-image-wrap character-group-parent-image">
                              {parentImageUrl ? (
                                <img src={parentImageUrl} alt={detail.parent.character_tag} />
                              ) : (
                                <div className="review-image-slot review-image-slot--empty">
                                  <span className="review-image-placeholder">No image</span>
                                </div>
                              )}
                              {isCharacterRegenerating(detail.parent.id) ? (
                                <div className="v2-review-card-regenerate-banner">
                                  <span>재생성 중...</span>
                                </div>
                              ) : null}
                            </div>
                            <h3 className="character-group-card-tag">{detail.parent.character_tag}</h3>
                            {detail.parent.display_name ? <p className="catalog-card-subtitle">{detail.parent.display_name}</p> : null}
                            <div className="character-group-card-meta">
                              <button
                                type="button"
                                className={genderChipClass(parentEffectiveGender)}
                                disabled={isCharacterRegenerating(detail.parent.id)}
                                onClick={() => stageGender(detail.parent.id, parentEffectiveGender)}
                              >
                                {genderChipLabel(parentEffectiveGender)}
                              </button>
                              <span className="badge badge-muted">posts {detail.parent.post_count.toLocaleString()}</span>
                              <span className="badge badge-muted">자식 {detail.children.length}</span>
                            </div>
                            <ReviewRatingStars rating={parentEffectiveRating} onRate={(r) => stageRating(detail.parent.id, r)} />
                          </div>

                          <div ref={childrenGridRef} className="character-group-children-grid">
                            {entries.length === 0 ? (
                              <div className="empty-state">기존 자식 또는 제안된 후보가 없습니다.</div>
                            ) : (
                              entries.map((entry) => {
                                const isStagedAccept = stagedActions[entry.member.id]?.op === "accept" || stagedActions[entry.member.id]?.op === "add";
                                const childStaged = stagedMemberEdits[entry.member.id];

                                // For raw (unstaged) suggestions, do NOT inherit parent rating!
                                const effectiveRating = entry.kind === "suggested" && !isStagedAccept
                                  ? resolveRating(entry.member, null, childStaged)
                                  : resolveRating(entry.member, parentEffectiveRating, childStaged);

                                const isCompleteStaged = stagedCompletes.has(entry.member.id);
                                const isRegenerating = isCharacterRegenerating(entry.member.id);

                                return (
                                  <ChildCard
                                    key={entry.key}
                                    entry={entry}
                                    staged={stagedActions[entry.member.id]}
                                    stagedEdit={stagedMemberEdits[entry.member.id]}
                                    parentRating={entry.kind === "suggested" && !isStagedAccept ? null : parentEffectiveRating}
                                    parentGender={parentEffectiveGender}
                                    isCompleteStaged={isCompleteStaged}
                                    isRegenerating={isRegenerating}
                                    selected={entry.key === selectedChildKey}
                                    onSelect={() => setSelectedChildKey(entry.key)}
                                    onAccept={() => handleAccept(entry.member.id)}
                                    onReject={() => handleReject(entry.member.id)}
                                    onUnlink={() => handleUnlink(entry.member.id)}
                                    onMove={() => setMoveChildTarget(entry.member)}
                                    onUndo={() => undoAction(entry.member.id)}
                                    onRate={(r) => stageRating(entry.member.id, r)}
                                    onCycleGender={(curG) => stageGender(entry.member.id, curG)}
                                    onToggleComplete={() => toggleStageComplete(entry.member.id, entry.member, effectiveRating)}
                                  />
                                );
                              })
                            )}
                          </div>
                        </>
                      );
                    })()}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

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
