import type { CollectJob } from "../types";

interface GenerationProgressPanelProps {
  job: CollectJob;
  onDismiss?: () => void;
  onCancel?: () => void;
  onPause?: () => void;
  onResume?: () => void;
}

function getProgressPercent(job: CollectJob): number | null {
  if (job.status === "completed") return 100;
  if (job.total > 0) return Math.min(100, Math.round((job.current / job.total) * 100));
  return null;
}

export function GenerationProgressPanel({ job, onDismiss, onCancel, onPause, onResume }: GenerationProgressPanelProps) {
  const percent = getProgressPercent(job);
  const isActive = job.status === "running" || job.status === "paused";
  const isDone = job.status === "completed" || job.status === "cancelled";

  const metaParts: string[] = [];
  if (isActive && job.total > 0 && percent !== null) {
    metaParts.push(`${job.current}/${job.total} ${percent}%`);
  }
  if (isDone && job.completed) metaParts.push(`저장 ${job.completed}`);
  if (job.failed) metaParts.push(`실패 ${job.failed}`);

  return (
    <div
      className={`task-card${job.status === "failed" ? " task-card-error" : ""}${isDone ? " task-card-done" : ""}${job.status === "paused" ? " task-card-paused" : ""}`}
    >
      {/* 행 1: 이름 · 배지 · 메타 · 버튼 */}
      <div className="task-row1">
        {job.status === "running" ? (
          <span className="job-running-indicator task-dot" aria-hidden="true" />
        ) : job.status === "paused" ? (
          <span className="task-dot task-dot-paused" aria-hidden="true">⏸</span>
        ) : null}
        <strong className="task-name" title={job.series_tag || "Series"}>
          {job.series_tag || "Series"}
        </strong>
        <span className="badge badge-compact badge-muted task-badge">생성</span>
        <span className="badge badge-compact task-badge">L{job.prompt_level ?? 1}</span>
        {metaParts.length > 0 ? (
          <span className="task-meta">{metaParts.join(" · ")}</span>
        ) : null}
        <div className="task-row1-spacer" />
        {job.status === "running" && onPause ? (
          <button className="btn btn-small btn-ghost task-btn" type="button" aria-label="일시정지" title="일시정지" onClick={onPause}>⏸</button>
        ) : null}
        {job.status === "running" && onCancel ? (
          <button className="btn btn-small btn-ghost task-btn" type="button" aria-label="취소" onClick={onCancel}>×</button>
        ) : null}
        {job.status === "queued" && onCancel ? (
          <button className="btn btn-small btn-ghost task-btn" type="button" aria-label="대기 취소" onClick={onCancel}>×</button>
        ) : null}
        {job.status === "paused" && onResume ? (
          <button className="btn btn-small btn-ghost task-btn" type="button" aria-label="재개" title="재개" onClick={onResume}>▶</button>
        ) : null}
        {job.status === "paused" && onCancel ? (
          <button className="btn btn-small btn-ghost task-btn" type="button" onClick={onCancel}>×</button>
        ) : null}
        {onDismiss ? (
          <button className="btn btn-small btn-ghost task-btn" type="button" onClick={onDismiss}>×</button>
        ) : null}
      </div>

      {/* 행 2: 메시지(좌 50%) + 프로그레스바(우 50%) */}
      {isActive ? (
        <div className="task-row2">
          <span className="task-msg" title={job.message}>{job.message || ""}</span>
          <div className={`task-bar${percent === null ? " task-bar-indeterminate" : ""}`}>
            <div
              className="task-bar-fill"
              style={percent !== null ? { width: `${percent}%` } : undefined}
            />
          </div>
        </div>
      ) : null}

      {job.error ? <div className="progress-panel-error-line task-error-line">{job.error}</div> : null}
    </div>
  );
}
