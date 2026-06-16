interface ReviewRatingStarsProps {
  rating: number | null;
  onRate: (value: number) => void;
}

export function ReviewRatingStars({ rating, onRate }: ReviewRatingStarsProps) {
  if (rating === -1) {
    return (
      <div className="review-rating-stars">
        <button
          type="button"
          className="review-star review-star--red review-star--active"
          onClick={() => onRate(-1)}
          aria-label="rating -1"
          title="rating -1 (다시 누르면 해제)"
        >
          ★
        </button>
      </div>
    );
  }

  return (
    <div className="review-rating-stars">
      <button
        type="button"
        className="review-star review-star--red"
        onClick={() => onRate(-1)}
        aria-label="rating -1"
        title="rating -1"
      >
        ★
      </button>
      <div className="review-rating-stars-main" aria-label="rating 0-6">
        {Array.from({ length: 6 }, (_, index) => {
          const starValue = index + 1;
          const isYellow = rating !== null && rating > 0 && starValue <= rating;
          const isExplicitZero = rating === 0;
          const className = [
            "review-star",
            isYellow ? "review-star--yellow review-star--active" : "",
            isExplicitZero || (rating !== null && !isYellow) ? "review-star--black" : "",
            rating === null ? "review-star--unset" : "",
          ]
            .filter(Boolean)
            .join(" ");

          return (
            <button
              key={starValue}
              type="button"
              className={className}
              onClick={() => onRate(starValue)}
              aria-label={`rating ${starValue}`}
              title={`rating ${starValue}`}
            >
              ★
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function toggleRating(current: number | null, next: number): number | null {
  return current === next ? null : next;
}
