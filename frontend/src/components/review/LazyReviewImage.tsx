import { useEffect, useRef, useState } from "react";
import { pendingReviewImageUrl } from "../../utils/reviewImages";

interface LazyReviewImageProps {
  imagePath: string;
  alt: string;
  active?: boolean;
  eager?: boolean;
  selected?: boolean;
  previewAnchor?: boolean;
  thumbSize?: number;
  onClick?: () => void;
}

export function LazyReviewImage({
  imagePath,
  alt,
  active = false,
  eager = false,
  selected = false,
  previewAnchor = false,
  thumbSize,
  onClick,
}: LazyReviewImageProps) {
  const rootRef = useRef<HTMLButtonElement>(null);
  const [visible, setVisible] = useState(eager);
  const src = pendingReviewImageUrl(imagePath, thumbSize ? { thumbnail: true, thumbSize } : undefined);

  useEffect(() => {
    if (eager) {
      setVisible(true);
      return;
    }

    const node = rootRef.current;
    if (!node) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          setVisible(entry.isIntersecting);
        }
      },
      { rootMargin: "240px 0px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [eager]);

  const className = [
    "review-image-slot",
    active ? "review-image-slot--active" : "",
    selected ? "review-image-slot--selected" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      ref={rootRef}
      type="button"
      className={className}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === " " || event.code === "Space") {
          event.preventDefault();
        }
      }}
      data-preview-anchor={previewAnchor ? "true" : undefined}
      title={`${alt} (Space로 확대)`}
    >
      {visible && src ? (
        <img src={src} alt={alt} loading={eager ? "eager" : "lazy"} decoding="async" />
      ) : (
        <span className="review-image-placeholder" />
      )}
    </button>
  );
}
