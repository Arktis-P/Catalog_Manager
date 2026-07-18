export type V2ReviewCardSize = "small" | "medium" | "large";

export const V2_REVIEW_CARD_SIZE_PRESETS_PX: Record<V2ReviewCardSize, number> = {
  small: 220,
  medium: 300,
  large: 420,
};

const STORAGE_KEY_SIZE = "v2_review_card_size";
const STORAGE_KEY_WIDTH_PX = "v2_review_card_width_px";
const CHANGE_EVENT = "v2-review-card-settings-changed";

function isCardSize(value: string | null): value is V2ReviewCardSize {
  return value === "small" || value === "medium" || value === "large";
}

// SettingsPage/V2ReviewPanel 양쪽에서 즉시 반영되도록 브라우저 로컬 저장소에
// 카드 크기 설정을 두고, 변경 시 커스텀 이벤트로 열려 있는 V2 패널에 알린다.
// 백엔드 settings_service.py/schemas/settings.py에도 동일한 키를 추가해 두었지만
// (F5 스코프상 routers/settings.py는 수정 대상이 아니라 PATCH로는 아직 저장되지 않는다),
// 최초 진입 시 서버 기본값을 읽어와 로컬 값이 없을 때의 기본값으로만 사용한다.
export function getV2ReviewCardSize(): V2ReviewCardSize | null {
  const raw = window.localStorage.getItem(STORAGE_KEY_SIZE);
  return isCardSize(raw) ? raw : null;
}

export function setV2ReviewCardSize(size: V2ReviewCardSize): void {
  window.localStorage.setItem(STORAGE_KEY_SIZE, size);
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT));
}

export function getV2ReviewCardWidthPx(): number | null {
  const raw = window.localStorage.getItem(STORAGE_KEY_WIDTH_PX);
  if (!raw) {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function setV2ReviewCardWidthPx(widthPx: number): void {
  window.localStorage.setItem(STORAGE_KEY_WIDTH_PX, String(Math.max(0, Math.round(widthPx))));
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT));
}

export function resolveV2ReviewCardWidthPx(size: V2ReviewCardSize, customWidthPx: number): number {
  return customWidthPx > 0 ? customWidthPx : V2_REVIEW_CARD_SIZE_PRESETS_PX[size];
}

export function onV2ReviewCardSettingsChanged(listener: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}
