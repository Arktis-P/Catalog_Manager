import type { CollectJob } from "../types";

interface CollectProgressPanelProps {
  job: CollectJob;
  onDismiss?: () => void;
  onCancel?: () => void;
}

function getProgressPercent(job: CollectJob): number | null {
  if (job.status === "completed") {
    return 100;
  }
  if (job.total > 0) {
    return Math.min(100, Math.round((job.current / job.total) * 100));
  }
  return null;
}

function phaseShortLabel(phase: string): string {
  switch (phase) {
    case "discovering_wiki":
      return "위키";
    case "discovering_wiki_subseries":
      return "하위";
    case "discovering_pattern":
      return "패턴";
    case "discovering_posts_scan":
      return "tag";
    case "discovering_posts_verify":
      return "분류";
    case "discovering":
      return "발견";
    case "counting":
      return "count";
    case "extracting":
      return "외형";
    case "saving":
      return "저장";
    case "completed":
      return "완료";
    case "failed":
      return "실패";
    case "starting":
      return "시작";
    case "queued":
      return "대기";
    case "cancelled":
      return "취소";
    default:
      return "준비";
  }
}

function phaseFullLabel(phase: string): string {
  switch (phase) {
    case "discovering_wiki":
      return "위키 파싱";
    case "discovering_wiki_subseries":
      return "하위 시리즈";
    case "discovering_pattern":
      return "패턴 검색";
    case "discovering_posts_scan":
      return "포스트 스캔";
    case "discovering_posts_verify":
      return "태그 분류";
    case "counting":
      return "포스트 수 조회";
    case "extracting":
      return "외형 추출";
    case "saving":
      return "저장 중";
    case "starting":
      return "초기화";
    default:
      return phase;
  }
}

function phaseBadgeClass(phase: string): string {
  switch (phase) {
    case "discovering_wiki":
    case "discovering_wiki_subseries":
    case "discovering_pattern":
    case "discovering_posts_scan":
    case "discovering_posts_verify":
      return "job-phase-badge job-phase-wiki";
    case "counting":
      return "job-phase-badge job-phase-count";
    case "extracting":
      return "job-phase-badge job-phase-extract";
    case "saving":
      return "job-phase-badge job-phase-save";
    default:
      return "job-phase-badge job-phase-default";
  }
}

function formatEta(job: CollectJob): string | null {
  if (job.job_type === "appearance_extract") {
    if (job.phase !== "extracting" || job.total <= 0 || job.current <= 0) {
      return null;
    }
    const remaining = job.total - job.current;
    const seconds = remaining * 0.5;
    if (seconds < 60) {
      return `~${Math.ceil(seconds)}s`;
    }
    return `~${Math.ceil(seconds / 60)}m`;
  }
  if (job.phase !== "counting" || job.total <= 0 || job.current <= 0) {
    return null;
  }
  const remaining = job.total - job.current;
  const seconds = remaining * 0.5;
  if (seconds < 60) {
    return `~${Math.ceil(seconds)}s`;
  }
  return `~${Math.ceil(seconds / 60)}m`;
}

function formatCompactMeta(job: CollectJob, percent: number | null): string | null {
  const parts: string[] = [];
  if (job.job_type === "appearance_extract") {
    if (job.total > 0) {
      parts.push(`${job.current}/${job.total}${percent !== null ? ` ${percent}%` : ""}`);
    }
    if (job.status === "completed" && job.updated > 0) {
      parts.push(`updated ${job.updated}`);
    }
  } else if (job.total > 0) {
    parts.push(`${job.current}/${job.total}${percent !== null ? ` ${percent}%` : ""}`);
    if (
      (job.phase === "discovering_wiki" || job.phase === "discovering_wiki_subseries") &&
      job.discovered > 0
    ) {
      parts.push(`캐릭터 ${job.discovered}`);
    }
  } else if (job.discovered > 0) {
    parts.push(`discovered ${job.discovered}`);
  }
  const eta = formatEta(job);
  if (eta) {
    parts.push(eta);
  }
  if (job.status === "completed" && job.job_type === "character_collect") {
    parts.push(`+${job.created}`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

function jobTypeLabel(job: CollectJob): string {
  return job.job_type === "appearance_extract" ? "Appearance" : "Collect";
}

// ─── 실행 중인 작업 — 상세 카드 ──────────────────────────────────────────────

function RunningJobCard({ job, onCancel }: { job: CollectJob; onCancel?: () => void }) {
  const percent = getProgressPercent(job);
  const eta = formatEta(job);

  const statsLine: string[] = [];
  if (job.job_type === "character_collect") {
    if (job.total > 0) statsLine.push(`${job.current} / ${job.total}`);
    if (job.discovered > 0) statsLine.push(`발견 ${job.discovered}명`);
  } else {
    if (job.total > 0) statsLine.push(`${job.current} / ${job.total}명`);
    if (eta) statsLine.push(eta);
  }

  return (
    <div className="job-running-card">
      <div className="job-running-header">
        <span className="job-running-indicator" aria-hidden="true" />
        <strong className="job-running-series" title={job.series_tag}>
          {job.series_tag}
        </strong>
        <span className="badge badge-compact badge-muted">{jobTypeLabel(job)}</span>
        <span className={phaseBadgeClass(job.phase)}>{phaseFullLabel(job.phase)}</span>
        <div className="job-running-header-spacer" />
        {onCancel ? (
          <button
            className="btn btn-small btn-ghost"
            type="button"
            aria-label="작업 취소"
            title="작업 취소"
            onClick={onCancel}
          >
            ×
          </button>
        ) : null}
      </div>
      <div className="job-running-message" title={job.message}>
        {job.message}
      </div>
      <div className="job-running-progress-row">
        <div
          className={`progress-bar job-running-bar${percent === null ? " progress-bar-indeterminate" : ""}`}
        >
          <div
            className="progress-bar-fill"
            style={percent === null ? undefined : { width: `${percent}%` }}
          />
        </div>
        <span className="job-running-pct">{percent !== null ? `${percent}%` : ""}</span>
      </div>
      {statsLine.length > 0 ? (
        <div className="job-running-stats">{statsLine.join(" · ")}</div>
      ) : null}
      {job.error ? <div className="progress-panel-error-line">{job.error}</div> : null}
    </div>
  );
}

// ─── 대기 중인 작업 — 컴팩트 ────────────────────────────────────────────────

function QueuedJobRow({ job, onCancel }: { job: CollectJob; onCancel?: () => void }) {
  return (
    <div className="progress-panel progress-panel-compact">
      <div className="progress-panel-compact-row">
        <strong className="progress-panel-series" title={job.series_tag}>
          {job.series_tag}
        </strong>
        <span className="badge badge-compact badge-muted">{jobTypeLabel(job)}</span>
        <span className="badge badge-compact">{phaseShortLabel(job.phase)}</span>
        <span className="progress-panel-message-compact" title={job.message}>
          {job.message}
        </span>
        {onCancel ? (
          <button
            className="btn btn-small btn-ghost"
            type="button"
            aria-label="대기 취소"
            title="대기 취소"
            onClick={onCancel}
          >
            ×
          </button>
        ) : null}
      </div>
    </div>
  );
}

// ─── 완료 / 실패 / 취소 — 컴팩트 ────────────────────────────────────────────

function DoneJobRow({
  job,
  onDismiss,
}: {
  job: CollectJob;
  onDismiss?: () => void;
}) {
  const percent = getProgressPercent(job);
  const meta = formatCompactMeta(job, percent);

  return (
    <div
      className={`progress-panel progress-panel-compact${
        job.status === "failed" ? " progress-panel-error" : ""
      } progress-panel-done`}
    >
      <div className="progress-panel-compact-row">
        <strong className="progress-panel-series" title={job.series_tag}>
          {job.series_tag}
        </strong>
        <span className="badge badge-compact badge-muted">{jobTypeLabel(job)}</span>
        <span className="badge badge-compact">{phaseShortLabel(job.phase)}</span>
        <span className="progress-panel-message-compact" title={job.message}>
          {job.message}
        </span>
        {meta ? <span className="progress-panel-meta">{meta}</span> : null}
        {onDismiss ? (
          <button className="btn btn-small btn-ghost" type="button" onClick={onDismiss}>
            ×
          </button>
        ) : null}
      </div>
      {job.error ? <div className="progress-panel-error-line">{job.error}</div> : null}
    </div>
  );
}

// ─── 외부 공개 컴포넌트 ──────────────────────────────────────────────────────

export function CollectProgressPanel({ job, onDismiss, onCancel }: CollectProgressPanelProps) {
  if (job.status === "running") {
    return <RunningJobCard job={job} onCancel={onCancel} />;
  }
  if (job.status === "queued") {
    return <QueuedJobRow job={job} onCancel={onCancel} />;
  }
  return <DoneJobRow job={job} onDismiss={onDismiss} />;
}
