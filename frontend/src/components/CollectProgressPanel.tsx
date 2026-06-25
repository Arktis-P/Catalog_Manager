import type { CollectJob } from "../types";

interface CollectProgressPanelProps {
  job: CollectJob;
  onDismiss?: () => void;
  onCancel?: () => void;
  onPause?: () => void;
  onResume?: () => void;
}

// ─── 공통 유틸 ───────────────────────────────────────────────────────────────

export function getProgressPercent(job: CollectJob): number | null {
  if (job.status === "completed") return 100;
  if (job.total > 0) return Math.min(100, Math.round((job.current / job.total) * 100));
  return null;
}

export function phaseShortLabel(phase: string): string {
  switch (phase) {
    case "discovering_wiki": return "위키";
    case "discovering_wiki_subseries": return "하위";
    case "discovering_pattern": return "패턴";
    case "discovering_posts_scan": return "스캔";
    case "discovering_posts_verify": return "분류";
    case "counting": return "count";
    case "extracting": return "외형";
    case "saving": return "저장";
    case "completed": return "완료";
    case "failed": return "실패";
    case "cancelled": return "취소";
    case "queued": return "대기";
    case "starting": return "시작";
    case "paused": return "정지";
    default: return "준비";
  }
}

export function phaseFullLabel(phase: string): string {
  switch (phase) {
    case "discovering_wiki": return "위키 파싱";
    case "discovering_wiki_subseries": return "하위 시리즈";
    case "discovering_pattern": return "패턴 검색";
    case "discovering_posts_scan": return "포스트 스캔";
    case "discovering_posts_verify": return "태그 분류";
    case "counting": return "포스트 수 조회";
    case "extracting": return "외형 추출";
    case "saving": return "저장 중";
    case "starting": return "초기화";
    default: return phase;
  }
}

export function phaseBadgeClass(phase: string): string {
  switch (phase) {
    case "discovering_wiki":
    case "discovering_wiki_subseries":
    case "discovering_pattern":
    case "discovering_posts_scan":
    case "discovering_posts_verify":
      return "job-phase-badge job-phase-wiki";
    case "counting": return "job-phase-badge job-phase-count";
    case "extracting": return "job-phase-badge job-phase-extract";
    case "saving": return "job-phase-badge job-phase-save";
    default: return "job-phase-badge job-phase-default";
  }
}

export function jobTypeLabel(job: CollectJob): string {
  return job.job_type === "appearance_extract" ? "외형 태그 추출" : "캐릭터 수집";
}

function formatEta(job: CollectJob): string | null {
  const isExtract = job.job_type === "appearance_extract";
  if (isExtract && job.phase !== "extracting") return null;
  if (!isExtract && job.phase !== "counting") return null;
  if (job.total <= 0 || job.current <= 0) return null;
  const sec = (job.total - job.current) * 0.5;
  return sec < 60 ? `~${Math.ceil(sec)}s` : `~${Math.ceil(sec / 60)}m`;
}

// ─── 파이프라인 패널용 확장 카드 (export) ────────────────────────────────────

export function RunningJobCard({
  job,
  onCancel,
  onPause,
  onResume,
}: {
  job: CollectJob;
  onCancel?: () => void;
  onPause?: () => void;
  onResume?: () => void;
}) {
  const percent = getProgressPercent(job);
  const eta = formatEta(job);

  // x / y 카운트
  const countParts: string[] = [];
  if (job.total > 0) {
    countParts.push(`${job.current.toLocaleString()} / ${job.total.toLocaleString()}`);
  }
  if (job.job_type === "character_collect" && job.discovered > 0) {
    countParts.push(`발견 ${job.discovered}명`);
  }
  if (eta) countParts.push(eta);

  const countDisplay = countParts.join(" · ");

  return (
    <div className="job-running-card">
      {/* Row 1: 시리즈명 + 타입 + 취소 */}
      <div className="job-running-header">
        <span className="job-running-indicator" aria-hidden="true" />
        <strong className="job-running-series" title={job.series_tag}>
          {job.series_tag}
        </strong>
        <div className="job-running-header-spacer" />
        <span className="job-type-label">{jobTypeLabel(job)}</span>
        {job.status === "running" && onPause ? (
          <button
            className="btn btn-small btn-ghost"
            type="button"
            aria-label="일시정지"
            title="일시정지"
            onClick={onPause}
          >
            ⏸
          </button>
        ) : null}
        {job.status === "paused" && onResume ? (
          <button
            className="btn btn-small btn-ghost"
            type="button"
            aria-label="재개"
            title="재개"
            onClick={onResume}
          >
            ▶
          </button>
        ) : null}
        {onCancel ? (
          <button
            className="btn btn-small btn-ghost"
            type="button"
            aria-label="작업 취소"
            onClick={onCancel}
          >
            ×
          </button>
        ) : null}
      </div>

      {/* Row 2: 단계 배지 + 카운트 */}
      <div className="job-running-meta-row">
        <span className={phaseBadgeClass(job.phase)}>{phaseFullLabel(job.phase)}</span>
        <div className="job-running-meta-spacer" />
        {countDisplay ? (
          <span className="job-running-count">{countDisplay}</span>
        ) : null}
        {percent !== null && job.total > 0 ? (
          <span className="job-running-pct-badge">{percent}%</span>
        ) : null}
      </div>

      {/* Row 3: 프로그레스 바 */}
      <div
        className={`progress-bar job-running-bar${
          percent === null ? " progress-bar-indeterminate" : ""
        }`}
      >
        <div
          className="progress-bar-fill"
          style={percent !== null ? { width: `${percent}%` } : undefined}
        />
      </div>

      {/* Row 4: 상세 메시지 */}
      {job.message ? (
        <div className="job-running-message" title={job.message}>
          {job.message}
        </div>
      ) : null}

      {job.error ? (
        <div className="progress-panel-error-line">{job.error}</div>
      ) : null}
    </div>
  );
}

// ─── GlobalTaskBar용 컴팩트 1줄 ──────────────────────────────────────────────

function CompactJobRow({
  job,
  onAction,
  actionLabel,
  onPause,
  onResume,
}: {
  job: CollectJob;
  onAction?: () => void;
  actionLabel?: string;
  onPause?: () => void;
  onResume?: () => void;
}) {
  const percent = getProgressPercent(job);
  const eta = formatEta(job);

  const meta: string[] = [];
  if (job.total > 0 && percent !== null && job.status !== "completed") {
    meta.push(`${percent}%`);
  }
  if (job.status === "running" && job.job_type === "character_collect" && job.discovered > 0) {
    meta.push(`${job.discovered}발견`);
  }
  if (job.status === "running" && eta) {
    meta.push(eta);
  }
  if (job.status === "completed" && job.job_type === "character_collect" && job.created > 0) {
    meta.push(`+${job.created}`);
  }
  if (job.status === "completed" && job.job_type === "appearance_extract" && job.updated > 0) {
    meta.push(`+${job.updated}`);
  }

  return (
    <div
      className={`progress-panel progress-panel-compact${
        job.status === "failed" ? " progress-panel-error" : ""
      }${
        job.status === "paused" ? " progress-panel-paused" : ""
      }${
        job.status === "completed" || job.status === "cancelled"
          ? " progress-panel-done"
          : ""
      }`}
    >
      <div className="progress-panel-compact-row">
        {job.status === "running" ? (
          <span className="job-running-indicator job-indicator-inline" aria-hidden="true" />
        ) : null}
        {job.status === "paused" ? (
          <span className="job-paused-indicator job-indicator-inline" aria-hidden="true" title="일시정지됨">⏸</span>
        ) : null}
        <strong className="progress-panel-series" title={job.series_tag}>
          {job.series_tag}
        </strong>
        <span className="badge badge-compact badge-muted">
          {job.job_type === "appearance_extract" ? "외형" : "수집"}
        </span>
        <span
          className={
            job.status === "running"
              ? phaseBadgeClass(job.phase)
              : "badge badge-compact"
          }
        >
          {phaseShortLabel(job.status === "running" ? job.phase : job.status)}
        </span>
        <span className="progress-panel-message-compact" title={job.message}>
          {job.message}
        </span>
        {meta.length > 0 ? (
          <span className="progress-panel-meta">{meta.join(" · ")}</span>
        ) : null}
        {job.status === "running" && onPause ? (
          <button
            className="btn btn-small btn-ghost"
            type="button"
            aria-label="일시정지"
            title="일시정지"
            onClick={onPause}
          >
            ⏸
          </button>
        ) : null}
        {job.status === "paused" && onResume ? (
          <button
            className="btn btn-small btn-ghost"
            type="button"
            aria-label="재개"
            title="재개"
            onClick={onResume}
          >
            ▶
          </button>
        ) : null}
        {onAction ? (
          <button
            className="btn btn-small btn-ghost"
            type="button"
            aria-label={actionLabel}
            onClick={onAction}
          >
            ×
          </button>
        ) : null}
      </div>
      {job.status === "running" && (
        <div className={`progress-bar compact-progress-bar${percent === null ? " progress-bar-indeterminate" : ""}`}>
          <div
            className="progress-bar-fill"
            style={percent !== null ? { width: `${percent}%` } : undefined}
          />
        </div>
      )}
      {job.error ? (
        <div className="progress-panel-error-line">{job.error}</div>
      ) : null}
    </div>
  );
}

// ─── 외부 공개 컴포넌트 (GlobalTaskBar 전용) ─────────────────────────────────

export function CollectProgressPanel({
  job,
  onDismiss,
  onCancel,
  onPause,
  onResume,
}: CollectProgressPanelProps) {
  const isDone =
    job.status === "completed" ||
    job.status === "failed" ||
    job.status === "cancelled";
  return (
    <CompactJobRow
      job={job}
      onAction={
        isDone
          ? onDismiss
          : job.status === "queued" || job.status === "running" || job.status === "paused"
            ? onCancel
            : undefined
      }
      actionLabel={isDone ? "닫기" : "취소"}
      onPause={job.status === "running" ? onPause : undefined}
      onResume={job.status === "paused" ? onResume : undefined}
    />
  );
}
