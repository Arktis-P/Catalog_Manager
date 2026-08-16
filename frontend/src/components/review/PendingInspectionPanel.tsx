import { useCallback, useEffect, useRef, useState } from "react";

type InspectionStats = {
  pending_with_image: number;
  remaining: number;
  current: number;
  inspection_version: string;
};

type InspectionSummary = {
  inspected: number;
  profile_built: number;
  rejected: number;
  characters_regenerated: number;
  regeneration_images: number;
  rejected_files_removed: number;
  auto_completed: number;
  audit_kept_pending: number;
  suggested_only: number;
  ratings: Record<string, number>;
  errors: string[];
};

const BATCH_SIZE = 10;

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function PendingInspectionPanel() {
  const [stats, setStats] = useState<InspectionStats | null>(null);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stopRequested = useRef(false);

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
    setRunning(true);
    setError(null);

    let inspected = 0;
    let regenerated = 0;
    let autoCompleted = 0;
    let audit = 0;
    let filesRemoved = 0;
    let errors = 0;

    try {
      let current = await loadStats();
      while (current.remaining > 0 && !stopRequested.current) {
        setMessage(
          `자동 검사 중 · 남은 ${current.remaining.toLocaleString()}개 · 한 번에 ${BATCH_SIZE}개씩 처리`,
        );
        const query = new URLSearchParams({
          limit: String(BATCH_SIZE),
          auto_regenerate: "true",
          max_regenerations: "2",
          auto_complete: "true",
          audit_sample_rate: "0.10",
          cleanup_rejected: "true",
        });
        const response = await fetch(`/api/review/v2/pending-inspection/run?${query.toString()}`, {
          method: "POST",
        });
        const result = await readJson<InspectionSummary>(response);
        inspected += result.inspected;
        regenerated += result.characters_regenerated;
        autoCompleted += result.auto_completed;
        audit += result.audit_kept_pending;
        filesRemoved += result.rejected_files_removed;
        errors += result.errors.length;
        current = await loadStats();

        setMessage(
          `검사 ${inspected.toLocaleString()} · 재생성 ${regenerated.toLocaleString()} · 자동완료 ${autoCompleted.toLocaleString()} · ` +
            `10% 검증대기 ${audit.toLocaleString()} · 불필요 이미지 삭제 ${filesRemoved.toLocaleString()}${errors ? ` · 오류 ${errors}` : ""}`,
        );
      }

      if (stopRequested.current) {
        setMessage(
          `일시정지됨 · 검사 ${inspected.toLocaleString()} · 재생성 ${regenerated.toLocaleString()} · 자동완료 ${autoCompleted.toLocaleString()}`,
        );
      } else {
        setMessage(
          `자동 검사 완료 · 검사 ${inspected.toLocaleString()} · 재생성 ${regenerated.toLocaleString()} · 자동완료 ${autoCompleted.toLocaleString()} · ` +
            `검증 샘플 ${audit.toLocaleString()}개는 pending에 남겼습니다.`,
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "pending 자동 검사 중 오류가 발생했습니다.");
      await loadStats().catch(() => undefined);
    } finally {
      setRunning(false);
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
            완료된 리뷰는 건드리지 않습니다. 기존 1장을 검사하고 명백한 실패만 최대 2회 재생성하며,
            참조 이미지는 저장하지 않고 Danbooru 태그 통계만 작은 캐시로 사용합니다.
          </div>
          <div style={{ marginTop: 6 }}>
            검사 완료 {stats.current.toLocaleString()} / {stats.pending_with_image.toLocaleString()} · 남음{" "}
            <strong>{stats.remaining.toLocaleString()}</strong>
          </div>
          {message ? <div style={{ marginTop: 6 }}>{message}</div> : null}
          {error ? <div className="alert alert-error" style={{ marginTop: 6 }}>{error}</div> : null}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {running ? (
            <button type="button" className="btn" onClick={stop}>
              현재 배치 후 중지
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              disabled={stats.remaining <= 0}
              onClick={() => void run()}
            >
              남은 Pending 자동 검사
            </button>
          )}
          <button type="button" className="btn" disabled={running} onClick={() => void loadStats()}>
            상태 새로고침
          </button>
        </div>
      </div>
    </section>
  );
}
