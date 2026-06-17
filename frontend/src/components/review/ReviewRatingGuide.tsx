const RATING_ROWS = [
  { grade: -1, name: "대상 아님", criteria: "남캐·비인간·여성형으로 보기 어려움" },
  { grade: 0, name: "생성 불가", criteria: "태그로 정상 생성되지 않음" },
  { grade: 1, name: "기피 여캐", criteria: "여캐지만 혐오·기피 요소 있음" },
  { grade: 2, name: "기본 여캐", criteria: "호감 요소 없음, 그냥 여캐" },
  { grade: 3, name: "잠재 호감", criteria: "외형·분위기·속성 중 호감 요소 있음" },
  { grade: 4, name: "검증 호감", criteria: "생성 결과 확인, 다시 나와도 좋음" },
  { grade: 5, name: "선호", criteria: "직접 골라 반복 생성 가능" },
  { grade: 6, name: "최선호", criteria: "특별 대우·변주 생성의 핵심" },
] as const;

export function ReviewRatingGuide() {
  return (
    <details className="review-rating-guide">
      <summary className="review-rating-guide-summary">
        <span className="review-rating-guide-title">평점 기준</span>
        <span className="review-rating-guide-hint">
          -1 대상 아님 · 0 생성 불가 · 1~2 보통 · 3 잠재 · 4 검증 · 5~6 선호
        </span>
      </summary>
      <div className="review-rating-guide-body">
        <table className="review-rating-guide-table">
          <thead>
            <tr>
              <th scope="col">등급</th>
              <th scope="col">이름</th>
              <th scope="col">기준</th>
            </tr>
          </thead>
          <tbody>
            {RATING_ROWS.map((row) => (
              <tr key={row.grade}>
                <td className="review-rating-guide-grade">{row.grade}</td>
                <td className="review-rating-guide-name">{row.name}</td>
                <td>{row.criteria}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
