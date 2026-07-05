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
}

export function ReviewShortcutGuide({ includeUndo = false }: ReviewShortcutGuideProps) {
  const shortcuts = includeUndo
    ? [...BASE_SHORTCUTS, "Ctrl+Z 취소", ...TAIL_SHORTCUTS]
    : [...BASE_SHORTCUTS, ...TAIL_SHORTCUTS];

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
