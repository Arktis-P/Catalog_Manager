const BASE_SHORTCUTS = [
  "←→ 이미지",
  "↑↓ 캐릭터",
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
}

export function ReviewShortcutGuide({
  includeUndo = false,
  includeMerge = false,
  includeMulticolor = false,
}: ReviewShortcutGuideProps) {
  const shortcuts = [
    ...BASE_SHORTCUTS,
    ...(includeUndo ? ["Ctrl+Z 취소"] : []),
    ...(includeMerge ? ["a Merge (부모/자식 연결)"] : []),
    ...(includeMulticolor ? ["c Multicolor 옵션 팝업"] : []),
    ...TAIL_SHORTCUTS,
  ];

  return (
    <details className="review-shortcut-guide">
      <summary className="review-shortcut-guide-summary">
        <span className="review-shortcut-guide-title">단축키</span>
        <span className="review-shortcut-guide-hint">←→↑↓ 이동 · Enter 완료 · r 재생성 · g 성별</span>
      </summary>
      <div className="review-shortcut-guide-body">
        {shortcuts.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>
    </details>
  );
}
