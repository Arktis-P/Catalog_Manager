# Review workflow acceleration

## Fast non-human review

1. Score existing characters once from the repository root:

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\v2_recalculate_non_human.py --apply
   ```

2. Open **Review > V2 review > Non-human candidate queue**.
3. Confirm the suggested rating with `Enter`, choose `-1` or `3` directly, or press `E` to return a false-positive candidate to normal V2 review.

The score and suggested rating only prioritize the queue. Confirming the final rating remains a user decision. Confirmed and excluded decisions are preserved by later recalculation.

## Fast parent/child linking

1. Build or refresh stored suggestions from the repository root:

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\v2_recalculate_character_link_suggestions.py --apply
   ```

2. Open **Review > Parent/child links**.
3. Select a pending or conflicting group. The parent is shown on the left; existing children and suggestions are shown on the right.
4. Stage accepts, rejections, unlinks, manual additions, or parent moves, then apply the group once. The whole group is rolled back if any relationship violates the one-level hierarchy rules.
5. Use **Recalculate group** to refresh only the selected parent. Rejected suggestions remain rejected.

The existing single-character link modal remains available for detailed linking from V2 review.
