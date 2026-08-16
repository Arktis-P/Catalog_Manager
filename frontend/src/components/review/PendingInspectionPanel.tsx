import { useCallback, useEffect, useRef, useState } from "react";

type InspectionStats = {
  pending_total: number;
  pending_with_image: number;
  pending_without_image: number;
  remaining: number;
  current: number;
  inspection_version: string;
};

type InspectionSummary = {
  requested_limit: number;
  inspected: number;
  profile_built: number;
  passed: number;
  warnings: number;
  rejected: number;
  characters_regenerated: number;
  regeneration_images: number;
  rejected_files_removed: number;
  auto_completed: number;
  audit_kept_pending: number;
  prefilled_pending: number;
  suggested_only: number;
  ratings: Record<string, number>;
  errors: string[];
};

type RunScope = "all" | "page" | null;

const BATCH_SIZE = 10;
const PAGE_TEST_LIMIT = 30;

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

function inspectionQuery(limit?: number): URLSearchParams {
  const query = new URLSearchParams({
    auto_regenerate: "true",
    max_regenerations: "2",
    auto_complete: "true",
    audit_sample_rate: "0.10",
    cleanup_rejected: "true",
  });
  if (limit != null) {
    query.set("limit", String(limit));
  }
  return query;
}

function currentPageCharacterIds(): number[] {
  const nodes = document.querySelectorAll<HTMLElement>(
    ".v2-review-grid:not(.v2-non-human-grid) [data-character-id]",
  );
  const ids: number[] = [];
  const seen = new Set<number>();
  for (const node of nodes) {
    if (node.offsetParent === null) continue;
    const id = Number(node.dataset.characterId);
    if (!Number.isFinite(id) || id <= 0 || seen.has(id)) continue;
    seen.add(id);
    ids.push(id);
    if (ids.length >= PAGE_TEST_LIMIT) break;
  }
  return ids;
}

export function PendingInspectionPanel() {
  const [stats, setStats] = useState<InspectionStats | null>(null);
  const [runScope, setRunScope] = useState<RunScope>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stopRequested = useRef(false);
  const running = runScope !== null;

  const loadStats = useCallback(async () => {
    const response = await fetch("/api/review/v2/pending-inspection/stats");
    const next = await readJson<InspectionStats>(response);
    setStats(next);
    return next;
  }, []);

  useEffect(() => {
    void loadStats().catch((err) => {
      setError(err instanceof Error ? err.message : "자동 검사 상태를 불러오지 못했습니다.");
    });
  }, [loadStats]);

  const stop = useCallback(() => {
    stopRequested.current = true;
    setMessage("현재 10개 배치가 끝나면 자동 검사를 멈춥니다.");
  }, []);

  const run = useCallback(async () => {
    if (running) return;
    stopRequested.current = false;
    setRunScope("all");
    setError(null);

    let inspected = 0;
    let regenerated = 0;
    let autoCompleted = 0;
    let audit = 0;
    let prefilled = 0;
    let filesRemoved = 0;
    let errors = 0;
    let stalled = false;

    try {
      let current = await loadStats();
      while (current.remaining > 0 && !stopRequested.current) {
        const beforeRemaining = current.remaining;
        setMessage(
          `자동 검사 중 · 남은 ${current.remaining.toLocaleString()}개 · 한 번에 ${BATCH_SIZE}개씩 처리`,
        );
        const query = inspectionQuery(BATCH_SIZE);
        const response = await fetch(`/api/review/v2/pending-inspection/run?${query.toString()}`, {
          method: "POST",
        });
        const result = await readJson<InspectionSummary>(response);
        inspected += result.inspected;
        regenerated += result.characters_regenerated;
        autoCompleted += result.auto_completed;
        audit += result.audit_kept_pending;
        prefilled += result.prefilled_pending;
        filesRemoved += result.rejected_files_removed;
        errors += result.errors.length;
        current = await loadStats();

        setMessage(
          `검사 ${inspected.toLocaleString()} · 재생성 ${regenerated.toLocaleString()} · 자동완료 ${autoCompleted.toLocaleString()} · ` +
            `평점 미리입력 ${prefilled.toLocaleString()} · 10% 검증대기 ${audit.toLocaleString()} · ` +
            `불필요 이미지 삭제 ${filesRemoved.toLocaleString()}${errors ? ` · 오류 ${errors}` : ""}`,
        );

        // A broken image, unavailable external service, or repeated DB error can leave
        // the same batch eligible forever. Stop rather than consuming API/local
        // resources indefinitely; the user can retry after resolving the displayed error.
        if (current.remaining >= beforeRemaining) {
          stalled = true;
          break;
        }
      }

      if (stopRequested.current) {
        setMessage(
          `일시정지됨 · 검사 ${inspected.toLocaleString()} · 재생성 ${regenerated.toLocaleString()} · 자동완료 ${autoCompleted.toLocaleString()}`,
        );
      } else if (stalled) {
        setError(
          `자동 검사가 같은 위치에서 더 진행되지 않아 안전하게 중지했습니다.${errors ? ` 누적 오류 ${errors}개를 확인하세요.` : " 상태를 새로고침한 뒤 다시 시도하세요."}`,
        );
      } else {
        setMessage(
          `자동 검사 완료 · 검사 ${inspected.toLocaleString()} · 재생성 ${regenerated.toLocaleString()} · 자동완료 ${autoCompleted.toLocaleString()} · ` +
            `평점 미리입력 ${prefilled.toLocaleString()} · 검증 샘플 ${audit.toLocaleString()}개는 pending에 남겼습니다.`,
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "pending 자동 검사 중 오류가 발생했습니다.");
      await loadStats().catch(() => undefined);
    } finally {
      setRunScope(null);
    }
  }, [loadStats, running]);

  const runCurrentPage = useCallback(async () => {
    if (running) return;
    const characterIds = currentPageCharacterIds();
    if (characterIds.length === 0) {
      setError("현재 화면에서 검사할 V2 카드의 ID를 찾지 못했습니다.");
      return;
    }

    setRunScope("page");
    setError(null);
    setMessage(`현재 페이지 ${characterIds.length.toLocaleString()}개를 테스트 검사 중입니다.`);
    try {
      const query = inspectionQuery();
      const response = await fetch(`/api/review/v2/pending-inspection/run-selected?${query.toString()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character_ids: characterIds }),
      });
      const result = await readJson<InspectionSummary>(response);
      await loadStats();
      const notEligible = Math.max(0, characterIds.length - result.inspected - result.errors.length);
      setMessage(
        `현재 페이지 테스트 완료 · 화면 ${characterIds.length.toLocaleString()}개 중 검사 ${result.inspected.toLocaleString()}개` +
          `${notEligible ? ` · 검사 대상 아님 ${notEligible.toLocaleString()}개` : ""}` +
          ` · 재생성 ${result.characters_regenerated.toLocaleString()} · 자동완료 ${result.auto_completed.toLocaleString()}` +
          ` · 평점 미리입력 ${result.prefilled_pending.toLocaleString()}` +
          `${result.errors.length ? ` · 오류 ${result.errors.length.toLocaleString()}` : ""}` +
          " · 아래 V2 목록은 새로고침하면 결과가 반영됩니다.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "현재 페이지 테스트 검사 중 오류가 발생했습니다.");
      await loadStats().catch(() => undefined);
    } finally {
      setRunScope(null);
    }
  }, [loadStats, running]);

  if (!stats) {
    return error ? <div className="alert alert-error">{error}</div> : null;
  }

  return (
    <section className="panel" aria-label="Pending 자동 검사">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
          padding: "12px 16px",
        }}
      >
        <div>
          <strong>Pending 자동 검사</strong>
          <div className="page-description" style={{ marginTop: 4 }}>
            완료된 리뷰는 건드리지 않습니다. 기존 이미지가 있는 Pending만 검사하며 명백한 실패만 최대 2회 재생성합니다.
            참조 이미지는 저장하지 않고 필요한 경우에만 Danbooru 태그 통계를 작은 캐시로 사용합니다.
          </div>
          <div style={{ marginTop: 6 }}>
            전체 리뷰 대기 <strong>{stats.pending_total.toLocaleString()}</strong> · 자동 검사 가능(이미지 있음){" "}
            <strong>{stats.pending_with_image.toLocaleString()}</strong> · 이미지 없음{" "}
            <strong>{stats.pending_without_image.toLocaleString()}</strong>
          </div>
          <div style={{ marginTop: 4 }}>
            자동 검사 완료 {stats.current.toLocaleString()} / {stats.pending_with_image.toLocaleString()} · 남음{" "}
            <strong>{stats.remaining.toLocaleString()}</strong>
          </div>
          {message ? <div style={{ marginTop: 6 }}>{message}</div> : null}
          {error ? <div className="alert alert-error" style={{ marginTop: 6 }}>{error}</div> : null}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {runScope === "all" ? (
            <button type="button" className="btn" onClick={stop}>
              현재 배치 후 중지
            </button>
          ) : (
            <>
              <button
                type="button"
                className="btn"
                disabled={running}
                onClick={() => void runCurrentPage()}
                title="아래 V2 검수 화면에 현재 표시된 카드 중 최대 30개만 먼저 검사합니다."
              >
                {runScope === "page" ? "현재 페이지 테스트 중..." : "현재 페이지 최대 30개 테스트"}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={running || stats.remaining <= 0}
                onClick={() => void run()}
              >
                남은 Pending 자동 검사
              </button>
            </>
          )}
          <button type="button" className="btn" disabled={running} onClick={() => void loadStats()}>
            상태 새로고침
          </button>
        </div>
      </div>
    </section>
  );
}
