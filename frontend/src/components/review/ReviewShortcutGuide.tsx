const MOVEMENT_SHORTCUTS = ["←→ 이미지", "↑↓ 캐릭터"] as const;
const V2_MOVEMENT_SHORTCUTS = ["←→↑↓ 카드 이동", "Ctrl+1-9 이미지 전환"] as const;

const BASE_SHORTCUTS = [
  "0-6 / - 레이팅 (재입력 시 해제)",
  "Enter 완료",
  "g 성별 순환 (girl-boy-no human-none)",
  "r 재생성 (NAIA · 기존 이미지 교체)",
] as const;

const TAIL_SHORTCUTS = ["q/w Danbooru", "Space 확대"] as const;

interface ReviewShortcutGuideProps {
  includeUndo?: boolean;
  includeMerge?: boolean;
  includeMulticolor?: boolean;
  v2Layout?: boolean;
}

export function ReviewShortcutGuide({
  includeUndo = false,
  includeMerge = false,
  includeMulticolor = false,
  v2Layout = false,
}: ReviewShortcutGuideProps) {
  const shortcuts = [
    ...(v2Layout ? V2_MOVEMENT_SHORTCUTS : MOVEMENT_SHORTCUTS),
    ...BASE_SHORTCUTS,
    ...(includeUndo ? ["Ctrl+Z 취소"] : []),
    ...(includeMerge ? ["a Merge (부모/자식 연결)"] : []),
    ...(includeMulticolor ? ["C: multicolor 전환"] : []),
    ...TAIL_SHORTCUTS,
  ];

  const hint = v2Layout
    ? "←→↑↓ 카드 이동 · Ctrl+1-9 이미지 전환 · Enter 완료 · r 재생성 · g 성별"
    : "←→↑↓ 이동 · Enter 완료 · r 재생성 · g 성별";

  return (
    <details className="review-shortcut-guide">
      <summary className="review-shortcut-guide-summary">
        <span className="review-shortcut-guide-title">단축키</span>
        <span className="review-shortcut-guide-hint">{hint}</span>
      </summary>
      <div className="review-shortcut-guide-body">
        {shortcuts.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>
    </details>
  );
}
