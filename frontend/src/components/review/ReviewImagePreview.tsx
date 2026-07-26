import { useEffect, useRef, useState } from "react";
import { getDanbooruReferenceImages, type DanbooruReferenceImage } from "../../api/reviewPipeline";
import "./reviewPipeline.css";

interface ReviewImagePreviewProps {
  src: string;
  alt: string;
  top?: number;
  left?: number;
  original?: boolean;
  fitToScreen?: boolean;
  onToggleFit?: () => void;
  onClose?: () => void;
  // When set (and original=true), fetch up to 3 Danbooru reference images for
  // side-by-side comparison against the generated/pending image.
  characterId?: number | null;
  characterTag?: string;
}

type ReferenceState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "ready"; images: DanbooruReferenceImage[] };

export function ReviewImagePreview({
  src,
  alt,
  top = 0,
  left = 0,
  original = false,
  fitToScreen = true,
  onToggleFit,
  onClose,
  characterId = null,
  characterTag,
}: ReviewImagePreviewProps) {
  const [references, setReferences] = useState<ReferenceState>({ status: "idle" });
  const requestIdRef = useRef(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!original || characterId == null) {
      setReferences({ status: "idle" });
      return;
    }
    const requestId = (requestIdRef.current += 1);
    const controller = new AbortController();
    setReferences({ status: "loading" });
    getDanbooruReferenceImages(characterId, 3, controller.signal)
      .then((response) => {
        if (requestIdRef.current !== requestId) {
          // A newer request superseded this one; discard the stale result.
          return;
        }
        if (response.error) {
          setReferences({ status: "error", message: response.error });
        } else if (response.images.length === 0) {
          setReferences({ status: "empty" });
        } else {
          setReferences({ status: "ready", images: response.images });
        }
      })
      .catch((err) => {
        if (requestIdRef.current !== requestId || controller.signal.aborted) {
          return;
        }
        setReferences({
          status: "error",
          message: err instanceof Error ? err.message : "Danbooru 참고 이미지를 불러오지 못했습니다.",
        });
      });
    return () => {
      controller.abort();
    };
  }, [original, characterId]);

  useEffect(() => {
    if (!original) {
      return;
    }
    previouslyFocusedRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const getFocusable = () =>
      Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );

    const first = getFocusable()[0];
    (first ?? dialogRef.current)?.focus({ preventScroll: true });

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose?.();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const focusable = getFocusable();
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const firstEl = focusable[0];
      const lastEl = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === firstEl) {
        event.preventDefault();
        lastEl.focus();
      } else if (!event.shiftKey && document.activeElement === lastEl) {
        event.preventDefault();
        firstEl.focus();
      }
    };

    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => {
      window.removeEventListener("keydown", onKeyDown, { capture: true });
      previouslyFocusedRef.current?.focus?.({ preventScroll: true });
    };
  }, [original, onClose]);

  if (!original) {
    return (
      <div className="review-image-preview" style={{ top, left }} aria-hidden="true">
        <img src={src} alt={alt} decoding="async" />
      </div>
    );
  }

  return (
    <>
      <div className="review-image-preview-original-backdrop" onClick={onClose} />
      <div
        ref={dialogRef}
        className="review-image-preview review-image-preview--original"
        role="dialog"
        aria-modal="true"
        aria-label={alt}
        tabIndex={-1}
      >
        <div className="review-image-preview-toolbar">
          {onToggleFit ? (
            <button type="button" className="btn btn-small" onClick={onToggleFit}>
              {fitToScreen ? "실제 크기" : "화면 맞춤"}
            </button>
          ) : null}
        </div>
        <div className="review-image-preview-body">
          <div className="review-image-preview-scroll">
            <img
              src={src}
              alt={alt}
              decoding="async"
              className={fitToScreen ? "review-image-preview-img--fit" : "review-image-preview-img--actual"}
            />
          </div>
          {characterId != null ? (
            <div className="review-image-preview-refs" aria-label="Danbooru 참고 이미지">
              <div className="review-image-preview-refs-title">Danbooru 참고 · {characterTag ?? ""}</div>
              {references.status === "loading" ? (
                <div className="review-image-preview-refs-grid">
                  {[0, 1, 2].map((index) => (
                    <div key={index} className="review-image-preview-ref-skeleton" />
                  ))}
                </div>
              ) : references.status === "error" ? (
                <div className="review-image-preview-refs-empty review-image-preview-refs-empty--error">
                  {references.message}
                </div>
              ) : references.status === "empty" ? (
                <div className="review-image-preview-refs-empty">참고 이미지가 없습니다.</div>
              ) : references.status === "ready" ? (
                <div className="review-image-preview-refs-grid">
                  {references.images.map((image) => {
                    const refSrc = image.preview_url ?? image.sample_url ?? image.file_url;
                    return (
                      <a
                        key={image.post_id}
                        className="review-image-preview-ref"
                        href={image.post_url}
                        target="_blank"
                        rel="noreferrer"
                        title={`Danbooru #${image.post_id}`}
                      >
                        {refSrc ? (
                          <img
                            src={refSrc}
                            alt={`${characterTag ?? alt} danbooru reference ${image.post_id}`}
                            loading="lazy"
                            decoding="async"
                          />
                        ) : (
                          <span className="review-image-placeholder">No preview</span>
                        )}
                      </a>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}
