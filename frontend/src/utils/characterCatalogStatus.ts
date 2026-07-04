const STATUS_LABELS: Record<string, string> = {
  uncollected: "미수집",
  queued: "대기",
  collecting: "수집 중",
  completed: "완료",
  partial: "부분 완료",
  failed: "실패",
  needs_review: "검토 필요",
};

export function collectStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function collectStatusBadgeClass(status: string): string {
  if (status === "completed") return "badge badge-success";
  if (status === "partial" || status === "needs_review" || status === "collecting" || status === "queued") {
    return "badge badge-warning";
  }
  if (status === "failed") return "badge badge-danger";
  return "badge";
}
