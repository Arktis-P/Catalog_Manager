import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { CharacterLinkCandidate, LinkableCharacterSummary } from "../types";
import { pendingReviewImageUrl } from "../utils/reviewImages";

const CANDIDATE_PREVIEW_SIZE = 600;

const MATCH_REASON_LABELS: Record<string, string> = {
  base_tag_match: "기본 태그 일치",
  same_series: "동일 시리즈",
  name_similarity: "이름 유사",
};

function matchReasonLabel(reason: string | null): string | null {
  if (!reason) {
    return null;
  }
  return MATCH_REASON_LABELS[reason] ?? reason;
}

type LinkMode = "as_child" | "as_parent";

interface CharacterLinkModalProps {
  character: LinkableCharacterSummary;
  onClose: () => void;
  onLinked: () => void;
}

export function CharacterLinkModal({ character, onClose, onLinked }: CharacterLinkModalProps) {
  const alreadyLinked = character.is_alternative;
  const canBeChild = !alreadyLinked && character.child_count === 0;

  const [mode, setMode] = useState<LinkMode>(canBeChild ? "as_child" : "as_parent");
  const [search, setSearch] = useState("");
  const [candidates, setCandidates] = useState<CharacterLinkCandidate[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewCandidate, setPreviewCandidate] = useState<CharacterLinkCandidate | null>(null);

  const effectiveMode: LinkMode = canBeChild ? mode : "as_parent";

  const selectedCandidate = useMemo(
    () => candidates.find((item) => item.id === selectedId) ?? null,
    [candidates, selectedId],
  );

  useEffect(() => {
    if (alreadyLinked) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.listCharacterLinkCandidates(character.id, {
          mode: effectiveMode === "as_child" ? "parent" : "child",
          search: search || undefined,
          limit: search ? 100 : 50,
        });
        if (cancelled) return;
        setCandidates(response.items);
        setSelectedId((current) => {
          if (current && response.items.some((item) => item.id === current)) {
            return current;
          }
          return response.items[0]?.id ?? null;
        });
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load link candidates");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [alreadyLinked, character.id, effectiveMode, search]);

  const handleClose = () => {
    if (submitting) return;
    onClose();
  };

  const moveSelection = (direction: 1 | -1) => {
    if (candidates.length === 0) return;
    const currentIndex = candidates.findIndex((item) => item.id === selectedId);
    const nextIndex =
      currentIndex === -1
        ? 0
        : (currentIndex + direction + candidates.length) % candidates.length;
    setSelectedId(candidates[nextIndex]!.id);
  };

  const handleUnlink = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await api.unlinkParentCharacter(character.id);
      onLinked();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to unlink character");
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmit = async () => {
    if (!selectedId) return;
    setSubmitting(true);
    setError(null);
    try {
      if (effectiveMode === "as_child") {
        await api.linkParentCharacter(character.id, selectedId);
      } else {
        await api.linkParentCharacter(selectedId, character.id);
      }
      onLinked();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to link character");
    } finally {
      setSubmitting(false);
    }
  };

  const isSubmitDisabled = !selectedId || submitting || (selectedCandidate ? !selectedCandidate.linkable : false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        if (previewCandidate) {
          setPreviewCandidate(null);
          return;
        }
        handleClose();
        return;
      }
      if (alreadyLinked) return;
      if (event.key === "ArrowUp") {
        event.preventDefault();
        event.stopPropagation();
        moveSelection(-1);
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        event.stopPropagation();
        moveSelection(1);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        event.stopPropagation();
        if (!isSubmitDisabled) {
          void handleSubmit();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [alreadyLinked, candidates, isSubmitDisabled, previewCandidate, selectedId, submitting]);

  return (
    <div className="modal-backdrop" onClick={handleClose}>
      <div className="modal modal-wide modal-merge" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header-row">
          <div className="modal-header-copy">
            <h2 className="modal-title">부모/자식 캐릭터 연결 — {character.display_name || character.character_tag}</h2>
            <p className="catalog-card-subtitle">
              의상 등으로 태그가 분리된 동일 캐릭터를 부모/자식 관계로 묶습니다. 자식 캐릭터에는 &quot;Alternative&quot; 태그가 부여됩니다.
            </p>
          </div>
          <button className="btn btn-small" type="button" disabled={submitting} onClick={handleClose}>
            Close
          </button>
        </div>

        <div className="modal-body-scroll">
          {alreadyLinked ? (
            <>
              <div className="field full-width">
                <label>현재 상위 캐릭터</label>
                <div className="catalog-card-subtitle">
                  {character.parent_display_name || character.parent_character_tag} ({character.parent_character_tag})
                </div>
              </div>
              {error ? <div className="error-banner">{error}</div> : null}
            </>
          ) : (
            <>
              {canBeChild ? (
                <div className="merge-mode-toggle">
                  <label>
                    <input
                      type="radio"
                      name="link-mode"
                      checked={mode === "as_child"}
                      disabled={submitting}
                      onChange={() => setMode("as_child")}
                    />
                    이 캐릭터를 다른 캐릭터의 하위(Alternative)로 연결
                  </label>
                  <label>
                    <input
                      type="radio"
                      name="link-mode"
                      checked={mode === "as_parent"}
                      disabled={submitting}
                      onChange={() => setMode("as_parent")}
                    />
                    다른 캐릭터를 이 캐릭터의 하위(Alternative)로 연결
                  </label>
                </div>
              ) : (
                <p className="catalog-card-subtitle">
                  이 캐릭터는 이미 하위 캐릭터를 가지고 있어 다른 캐릭터의 하위로는 연결할 수 없습니다. 하위 캐릭터를 추가하는 것만 가능합니다.
                </p>
              )}

              <div className="toolbar" style={{ marginBottom: 12 }}>
                <div className="field full-width">
                  <label htmlFor="link-search">
                    {effectiveMode === "as_child" ? "상위 캐릭터 검색" : "하위(Alternative) 캐릭터 검색"}
                  </label>
                  <input
                    id="link-search"
                    value={search}
                    disabled={submitting}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="character tag / 이름 입력"
                    autoComplete="off"
                    autoFocus
                  />
                </div>
              </div>

              {error ? <div className="error-banner">{error}</div> : null}

              <div className="field full-width">
                <label>{effectiveMode === "as_child" ? "연결될 상위 캐릭터" : "연결될 하위 캐릭터"}</label>
                {loading ? <div className="empty-state">후보 불러오는 중...</div> : null}
                {!loading ? (
                  <div className="merge-candidate-list" role="listbox" aria-label="link candidates">
                    {candidates.length === 0 ? (
                      <div className="empty-state">검색 조건에 맞는 캐릭터가 없습니다.</div>
                    ) : (
                      candidates.map((candidate) => {
                        const isSelected = candidate.id === selectedId;
                        return (
                          <button
                            key={candidate.id}
                            type="button"
                            role="option"
                            aria-selected={isSelected}
                            className={`merge-candidate-item${isSelected ? " merge-candidate-item-selected" : ""}${
                              !candidate.linkable ? " merge-candidate-item-disabled" : ""
                            }`}
                            disabled={submitting}
                            onClick={() => setSelectedId(candidate.id)}
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
                              <span
                                className={`merge-candidate-badge merge-candidate-badge--completed${
                                  candidate.cover_image_path ? " merge-candidate-badge--clickable" : ""
                                }`}
                                role={candidate.cover_image_path ? "button" : undefined}
                                title={
                                  candidate.cover_image_path
                                    ? "카탈로그에 표시 중 · 클릭하면 선택된 이미지를 크게 봅니다"
                                    : "카탈로그 선택 완료 (표시 이미지 없음)"
                                }
                                onClick={(event) => {
                                  if (!candidate.cover_image_path) return;
                                  event.stopPropagation();
                                  setPreviewCandidate(candidate);
                                }}
                              >
                                완료
                                {typeof candidate.rating === "number" ? ` ★${candidate.rating}` : ""}
                                {candidate.cover_image_path ? " · 이미지" : ""}
                              </span>
                            ) : candidate.image_count > 0 ? (
                              <span className="merge-candidate-badge" title="이미지는 생성됐지만 아직 리뷰 미완료">
                                생성됨 {candidate.image_count}장
                              </span>
                            ) : null}
                          </button>
                        );
                      })
                    )}
                  </div>
                ) : null}
              </div>
            </>
          )}
        </div>

        <div className="modal-actions merge-modal-actions">
          <div className="merge-modal-buttons">
            <button className="btn" type="button" disabled={submitting} onClick={handleClose}>
              Cancel
            </button>
            {alreadyLinked ? (
              <button className="btn btn-primary" type="button" disabled={submitting} onClick={() => void handleUnlink()}>
                {submitting ? "해제 중..." : "연결 해제"}
              </button>
            ) : (
              <button
                className="btn btn-primary"
                type="button"
                disabled={isSubmitDisabled}
                onClick={() => void handleSubmit()}
              >
                {submitting ? "연결 중..." : "연결"}
              </button>
            )}
          </div>
        </div>
      </div>
      {previewCandidate?.cover_image_path ? (
        <div
          className="merge-image-popup"
          onClick={(event) => {
            event.stopPropagation();
            setPreviewCandidate(null);
          }}
        >
          <div className="merge-image-popup-panel">
            <div className="merge-image-popup-caption">
              {previewCandidate.display_name || previewCandidate.character_tag}
              {typeof previewCandidate.rating === "number" ? ` · ★${previewCandidate.rating}` : ""}
            </div>
            <img
              src={
                pendingReviewImageUrl(previewCandidate.cover_image_path, {
                  thumbnail: true,
                  thumbSize: CANDIDATE_PREVIEW_SIZE,
                }) ?? undefined
              }
              alt={previewCandidate.character_tag}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
