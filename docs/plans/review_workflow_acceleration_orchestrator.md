# Review Workflow Acceleration — Local Orchestrator Instructions

## 1. Objective

Implement two workflow improvements on top of the current `master` branch:

1. Fast pre-review for likely non-human characters.
2. Group-based parent/child recommendation and editing.

The final objective is not automatic judgment. The system should reduce the number of clicks, key presses, and repeated decisions required from the user so that more characters can be reviewed per unit of time.

The user remains the final decision-maker for:

- whether a character is non-human,
- whether a humanoid/non-human female-like character should remain in the catalog,
- the final rating,
- parent/child relationship confirmation.

## 2. Branch and Delivery Rules

- Start from the latest `master`.
- Create and work only on a separate feature branch.
- Recommended implementation branch: `feature/review-workflow-acceleration`.
- Do not commit directly to `master`.
- Preserve existing review data and behavior.
- Prefer extending and reusing existing services, schemas, components, APIs, and tests over replacing them.
- Keep commits separated by feature or layer.

## 3. Mandatory Existing-Code Investigation

Before implementation, inspect the following areas and produce a compact reuse report containing file paths, reusable functions/components, required modifications, and major risks.

### V2 review

Inspect at least:

- `frontend/src/components/review/V2ReviewPanel.tsx`
- `frontend/src/components/review/V2ReviewRow.tsx`
- `frontend/src/components/review/V2SingleReviewOverlay.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/types/index.ts`
- `backend/app/routers/review.py`
- `backend/app/services/review_service.py`
- `backend/app/schemas/review.py`
- `backend/app/models/global_character.py`
- `backend/app/models/global_character_review.py`
- `backend/app/models/global_character_image.py`

Confirm:

- V2 list filters and pagination,
- pending/completed behavior,
- single and bulk save behavior,
- rating support for `-1`, `0`, and `1–6`,
- keyboard shortcut ownership,
- save-and-move-to-next behavior,
- image selection and latest/cover image fallback,
- whether image-less characters can be displayed.

### Non-human classification input

Inspect:

- `backend/app/integrations/danbooru/appearance_extractor.py`
- collection services that call the extractor,
- `GlobalCharacter` persistence and migrations.

Known current behavior to preserve:

- `gender` is normalized to `1girl`, `1boy`, or `no_humans`.
- `extract_gender()` compares the strongest non-human-related frequency against `1girl` and `1boy`.
- A non-human character may still be stored as `1girl` or `1boy` when those tags have higher related-tag frequency.

Do not replace the existing gender logic without a demonstrated need. Add candidate-ranking information alongside it.

### Parent/child linking

Inspect at least:

- `frontend/src/components/CharacterLinkModal.tsx`
- `backend/app/services/character_link_service.py`
- the related character-link router,
- `backend/app/models/global_character.py`,
- existing link and review-preservation tests.

Known reusable behavior:

- `parent_character_id`, `parent`, and `children`,
- parent/child linking and unlinking,
- candidate search,
- parent and child candidate modes,
- structural parent/child matching,
- base-name matching,
- name similarity,
- linkability validation,
- review status, rating, image count, and cover-image metadata,
- V2 parent and child status fields.

The existing single-character linking workflow must remain operational.

## 4. Feature A — Fast Non-Human Pre-Review

### Goal

Collect likely non-human characters into a focused queue before normal V2 review. The system proposes candidates and default actions; the user makes the final judgment.

### Core user actions

Each candidate should support three primary outcomes:

1. Non-human → save rating `-1`, complete review, move to next.
2. Non-human but female-like/humanoid and worth retaining → save rating `3`, complete review, move to next.
3. Not a non-human candidate → exclude from this queue while keeping the character in normal V2 pending review.

A hold/defer action may leave the candidate pending.

### Input-minimizing behavior

- The system may suggest a default rating.
- Obvious non-human candidates may default to `-1`.
- Female-like or humanoid candidates may default to `3`.
- Uncertain candidates should have no default.
- When the default is correct, `Enter` should confirm and move to the next item.
- Reuse existing image navigation and enlargement shortcuts.
- Add only the minimum additional shortcut required for “not a non-human candidate.”
- Verify all shortcuts against existing V2 shortcuts before assigning keys.

### Candidate selection

The candidate process should favor recall over precision. Use available signals such as:

- current normalized gender,
- `1girl`, `1boy`, and non-human-related frequencies,
- `no_humans`, `creature`, `animal`, `monster`, and related tags,
- series membership,
- presence or absence of normal appearance tags,
- previous user decisions.

Do not treat the candidate score as a final classification.

Thresholds must be defined in one configuration location rather than duplicated across services.

Do not introduce a machine-learning classifier in the first implementation.

### Persistence

Keep gender and non-human review state separate.

Preferred minimum fields or equivalent storage:

- `non_human_candidate_score`
- `non_human_suggested_rating`
- `non_human_review_status`

Recommended status values:

- `pending`
- `confirmed`
- `excluded`

Store source scores such as `girl_score`, `boy_score`, and `non_human_score` only if they materially improve recalculation, debugging, or UI explanation.

User decisions must survive candidate recalculation.

### Existing-data recalculation

Provide an explicit recalculation mechanism for existing `GlobalCharacter` records. Suitable forms include:

- a maintenance command,
- an admin API,
- a settings action,
- or an existing background-job framework.

Do not recalculate the full dataset on every application startup or every page request.

### UI

Prefer a V2 sub-mode or tab rather than a duplicated review system:

- General review
- Non-human pre-review

Reuse `V2ReviewRow`, `V2SingleReviewOverlay`, shared draft logic, image URL helpers, ratings, and save APIs wherever practical.

Hide or collapse unrelated controls such as detailed prompt editing in this fast mode.

The focused view should emphasize:

- generated image when available,
- character name and tag,
- series,
- current gender,
- concise candidate evidence,
- actions `-1`, `3`, and return to general V2 review.

Image-less candidates should still be reviewable using name, series, and collected tag information.

### Integration with normal V2 review

- Confirming `-1` or `3` should use the existing V2 review persistence where possible and mark the review completed.
- Excluding a candidate must not complete the normal review.
- Excluded candidates remain available in general V2 pending review.
- Pending candidates remain in the pre-review queue.

## 5. Feature B — Group Parent/Child Review

### Goal

Replace repeated one-character-at-a-time linking work with a group review screen while retaining the existing modal for manual or detailed searches.

### Layout

For each group:

- Left: one parent card with image, name, tag, review status, rating, and child count.
- Right: existing children and suggested children in approximately four cards per row.
- Show an image when one exists.
- Use cover image first, then latest generated image, then a compact image-less card or placeholder.

Visually distinguish:

- existing link,
- new suggestion,
- manually added candidate,
- pending removal/rejection,
- conflict.

### Default ordering and filters

Prioritize:

1. unreviewed suggestions,
2. candidates without existing relationships,
3. partially linked groups,
4. conflicts,
5. fully confirmed groups.

Useful filters:

- unreviewed suggestions,
- existing links,
- conflicts,
- all,
- has image,
- review pending,
- review completed.

Keep the default toolbar compact.

### Candidate generation

Reuse `CharacterLinkService` for:

- structural parent and child matching,
- base-tag matching,
- name similarity,
- search,
- linkability checks.

Keep the existing single-item candidate API for `CharacterLinkModal` and manual search.

Avoid calling the single-item API repeatedly for a whole large page if it creates excessive queries. Add a group-oriented or precomputed recommendation layer where necessary.

### Suggestion persistence

Separate unconfirmed suggestions from confirmed `parent_character_id` relationships.

Prefer a dedicated table or equivalent durable structure containing:

- parent candidate,
- child candidate,
- score,
- match reason,
- status,
- creation and review timestamps.

Recommended statuses:

- `pending`
- `accepted`
- `rejected`
- `superseded`

This state should support:

- prioritizing pending suggestions,
- preventing rejected pairs from immediately reappearing,
- recalculation,
- distinguishing existing links from proposals,
- invalidating stale suggestions after algorithm changes.

### User operations

Support within a group:

- add a child through search,
- reject a suggestion without affecting existing links,
- unlink an existing child,
- move a child to another parent,
- replace an incorrect parent,
- apply the group changes in one action.

Before applying, validate on the server:

- no self-link,
- no duplicate link,
- one parent per child,
- no cycle,
- existing one-level hierarchy restrictions,
- all referenced characters still exist,
- review-preservation rules remain intact.

Prefer a group transaction to preserve relationship consistency. If partial success is allowed, return explicit item-level results and ensure no invalid intermediate state remains.

### Recalculation

Provide:

- recalculate current group,
- recalculate all suggestions.

Full recalculation must use a background or maintenance workflow rather than blocking an interactive page request across the entire catalog.

## 6. Interaction Between the Features

Recommended user flow:

1. Non-human pre-review.
2. Parent/child relationship review.
3. General V2 review.

Do not enforce this order.

Investigate and preserve the current behavior for linking characters with existing single reviews. Specifically verify:

- what happens when reviewed parent and child records are linked,
- which images and ratings remain representative,
- whether completion state is preserved,
- whether non-human decisions survive link changes.

## 7. Sub-Agent Strategy

Use sub-agents aggressively for parallel discovery and verification, but minimize duplicated context and token use.

### Discovery agents

Assign non-overlapping scopes:

- Agent A: V2 frontend and review state flow.
- Agent B: related-tag extraction, non-human candidate data, migrations, recalculation.
- Agent C: parent/child service, routers, constraints, review-preservation behavior and tests.
- Agent D: UI/CSS review only if layout implementation needs separate design-system analysis.

Each discovery agent should return only:

- reusable files/functions,
- files requiring modification,
- state-flow risks,
- recommended implementation approach.

Do not ask multiple agents to inspect the same files unless one is explicitly performing a later review.

### Implementation agents

After the orchestrator consolidates discovery findings, split implementation by ownership:

- Backend non-human candidate model, migration, calculation, APIs, tests.
- Backend relationship suggestions, grouped APIs, transactions, tests.
- Frontend modes, screens, API wiring, keyboard behavior.
- Final verification and regression review.

Avoid simultaneous edits to shared router registration, model-registration, migration-head, and central type files without explicit ownership.

### Token-efficiency rules

- Give each agent exact paths and questions.
- Do not repeat the full repository background in every prompt.
- Request conclusions and symbol names rather than copied source files.
- Reuse the discovery report for implementation prompts.
- Send only relevant test failures to the fixing agent.
- Reserve strongest agents for transaction integrity, state interactions, and final review.
- Use lightweight agents for file discovery and straightforward UI wiring.

## 8. Implementation Sequence

1. Inspect existing code and produce the reuse report.
2. Finalize persistence, API, shortcut, and UI-entry decisions.
3. Implement non-human backend and tests.
4. Implement non-human fast-review UI.
5. Implement parent/child suggestion persistence, grouped APIs, transactions, and tests.
6. Implement grouped relationship-review UI.
7. Run integration and regression verification.
8. Add concise usage documentation.

Do not begin broad implementation before the discovery report has been consolidated.

## 9. Required Tests

### Non-human pre-review

- existing `no_humans` records become candidates,
- `1girl`/`1boy` records can still become candidates when non-human evidence crosses the threshold,
- ordinary human characters are not broadly over-selected,
- confirm `-1`,
- confirm `3`,
- exclude candidate while retaining general V2 pending state,
- confirmed/excluded decisions survive recalculation,
- image-less candidate display,
- ordering, filtering, and pagination,
- keyboard confirmation and next-item movement.

### Parent/child review

- display existing parent and children,
- structural candidate recommendation,
- base-name and name-similarity recommendation,
- candidates with and without images,
- add child,
- reject suggestion,
- unlink existing child,
- change parent,
- prevent multiple parents,
- prevent self-link and cycles,
- preserve one-level hierarchy restrictions,
- preserve existing completed review behavior,
- retain rejected state across recalculation,
- group transaction consistency.

### Regression

- general V2 list and single review,
- V2 rating and image selection,
- V2 bulk completion,
- current `CharacterLinkModal`,
- existing link and unlink endpoints,
- existing review-preservation tests,
- frontend typecheck and production build,
- migrations against an existing database.

## 10. Completion Criteria

The task is complete only when:

- likely non-human characters can be opened in a dedicated fast queue,
- the user can resolve the common case with one confirmation input,
- `-1`, `3`, and return-to-general-review actions work correctly,
- the system never presents its candidate score as a final judgment,
- pending parent/child suggestions are shown before settled groups,
- parent appears on the left and children/suggestions on the right,
- users can add, reject, unlink, move, and apply relationships from one screen,
- existing single-character linking remains functional,
- existing V2 behavior remains functional,
- migrations, tests, typecheck, and build pass,
- list endpoints avoid loading the full catalog and avoid obvious N+1 queries.

## 11. Final Report

Return a compact report containing:

1. implemented features,
2. reused existing functions/components/services,
3. major changed files,
4. migration summary,
5. tests and build results,
6. exact user workflow,
7. known limitations or deferred improvements.

Be explicit about any incomplete or provisional behavior.