const MULTI_COLOR_PROMPT_TAGS = new Set([
  "red_streaks",
  "orange_streaks",
  "blonde_streaks",
  "green_streaks",
  "aqua_streaks",
  "blue_streaks",
  "black_streaks",
  "grey_streaks",
  "white_streaks",
  "brown_streaks",
  "gradient_hair",
  "colored_inner_hair",
  "multicolored_hair",
  "two-tone_hair",
]);

// 자주 쓰는 멀티컬러 머리 옵션. 캐릭터에 태그가 없어도 항상 선택 버튼으로 노출한다.
// key는 appearanceTagChips의 multi 그룹과 동일한 형식이라 두 버튼이 자동 동기화된다.
export const MULTI_HAIR_OPTIONS = [
  "multicolored_hair",
  "two-tone_hair",
  "gradient_hair",
  "streaked_hair",
  "colored_inner_hair",
].map((tag) => ({
  tag,
  key: `multi:${tag}`,
  label: tag.replace(/_/g, " ").replace(/\s*hair$/, ""),
}));

export function stripHairSuffix(label: string): string {
  const stripped = label.replace(/\s*hair$/, "");
  return stripped || label;
}

function tagToPromptText(tag: string): string {
  return tag.trim().replace(/_/g, " ");
}

function characterTagToPromptName(characterTag: string): string {
  return characterTag.trim().replace(/_/g, " ");
}

export function weightedCharacterPrompt(characterTag: string): string {
  let name = characterTagToPromptName(characterTag);
  if (/\d$/.test(name)) {
    name = `${name} `;
  }
  return `1.2::${name}::`;
}

export function buildV2BasePrompt(
  characterTag: string,
  primaryHairColor?: string | null,
  promptCandidateMultiColorTags?: string[] | null,
): string {
  const parts = [
    ...(primaryHairColor ? [tagToPromptText(primaryHairColor)] : []),
    ...(promptCandidateMultiColorTags ?? []).map(tagToPromptText),
  ].filter(Boolean);
  return parts.length > 0
    ? `${weightedCharacterPrompt(characterTag)}, ${Array.from(new Set(parts)).join(", ")}`
    : weightedCharacterPrompt(characterTag);
}

function splitTags(value: string | null | undefined): string[] {
  if (!value) {
    return [];
  }
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

export function appearanceTagChips(item: {
  gender: string | null;
  multi_color_hair: string | null;
  hair_color: string | null;
  hair_shape: string | null;
  eye_color: string | null;
  feature_tags: string | null;
}): Array<{
  key: string;
  label: string;
  group: "gender" | "hair" | "multi" | "shape" | "eyes" | "features";
  optional?: boolean;
}> {
  const chips: Array<{
    key: string;
    label: string;
    group: "gender" | "hair" | "multi" | "shape" | "eyes" | "features";
    optional?: boolean;
  }> = [];

  if (item.gender) {
    chips.push({ key: `gender:${item.gender}`, label: item.gender, group: "gender" });
  }

  for (const tag of splitTags(item.hair_color)) {
    chips.push({ key: `hair:${tag}`, label: tagToPromptText(tag), group: "hair" });
  }

  for (const tag of splitTags(item.multi_color_hair)) {
    if (tag === "streaked_hair" || !MULTI_COLOR_PROMPT_TAGS.has(tag)) {
      continue;
    }
    chips.push({ key: `multi:${tag}`, label: tagToPromptText(tag), group: "multi" });
  }

  for (const tag of splitTags(item.hair_shape)) {
    chips.push({ key: `shape:${tag}`, label: tagToPromptText(tag), group: "shape" });
  }

  for (const tag of splitTags(item.eye_color)) {
    chips.push({ key: `eyes:${tag}`, label: tagToPromptText(tag), group: "eyes" });
  }

  for (const tag of splitTags(item.feature_tags)) {
    chips.push({ key: `features:${tag}`, label: tagToPromptText(tag), group: "features" });
  }

  // 캐릭터 데이터에 없는 멀티컬러 옵션도 chips에 포함시켜, 옵션 버튼으로 켰을 때
  // 프롬프트/selected_tags에 반영되게 한다. optional 표시로 기본 선택·상단 표시에서 제외.
  const existingKeys = new Set(chips.map((chip) => chip.key));
  for (const option of MULTI_HAIR_OPTIONS) {
    if (!existingKeys.has(option.key)) {
      chips.push({ key: option.key, label: tagToPromptText(option.tag), group: "multi", optional: true });
    }
  }

  return chips;
}

export function buildFinalPrompt(
  characterTag: string,
  basePrompt: string | null,
  enabledTagKeys: Set<string>,
  chips: ReturnType<typeof appearanceTagChips>,
): string | null {
  const innerParts: string[] = [];
  for (const chip of chips) {
    if (!enabledTagKeys.has(chip.key)) {
      continue;
    }
    if (chip.group === "gender") {
      continue;
    }
    innerParts.push(chip.label);
  }

  if (innerParts.length === 0) {
    return basePrompt ?? weightedCharacterPrompt(characterTag);
  }

  // generation_prompt가 비어 있어도(예: 아직 이미지 생성 job이 캐시하지 않은 GlobalCharacter)
  // 항목에 표시된 외형 태그만으로 기본 프롬프트를 구성해 보여준다.
  return `${weightedCharacterPrompt(characterTag)}, ${innerParts.join(", ")}`;
}

export function defaultEnabledTagKeys(
  chips: ReturnType<typeof appearanceTagChips>,
  promptCandidateMultiColorTags?: string[] | null,
): Set<string> {
  const enabled = new Set<string>();
  let primaryHairEnabled = false;
  const candidateMultiKeys = new Set(
    (promptCandidateMultiColorTags ?? []).map((tag) => `multi:${tag.trim()}`).filter((tag) => tag !== "multi:"),
  );

  for (const chip of chips) {
    if (chip.group === "hair") {
      if (!primaryHairEnabled) {
        enabled.add(chip.key);
        primaryHairEnabled = true;
      }
      continue;
    }
    if (chip.group === "multi" && (!chip.optional || candidateMultiKeys.has(chip.key))) {
      enabled.add(chip.key);
    }
  }

  return enabled;
}

export function selectedTagsPayload(
  item: {
    gender: string | null;
    multi_color_hair: string | null;
    hair_color: string | null;
    hair_shape: string | null;
    eye_color: string | null;
    feature_tags: string | null;
  },
  enabledTagKeys: Set<string>,
): string | null {
  const chips = appearanceTagChips(item);
  const enabled = enabledTagKeys.size > 0 ? enabledTagKeys : defaultEnabledTagKeys(chips);
  const rawTags = chips
    .filter((chip) => chip.group !== "gender" && enabled.has(chip.key))
    .map((chip) => chip.key.slice(chip.key.indexOf(":") + 1));
  return rawTags.length > 0 ? rawTags.join(",") : null;
}

export function genderChipClass(gender: string | null | undefined): string {
  if (gender === "1girl") {
    return "review-tag review-tag--girl";
  }
  if (gender === "1boy") {
    return "review-tag review-tag--boy";
  }
  if (gender === "no_humans") {
    return "review-tag review-tag--nonhuman";
  }
  return "review-tag review-tag--muted";
}

export function genderChipLabel(gender: string | null | undefined): string {
  if (gender === "1girl" || gender === "1boy" || gender === "no_humans") {
    return gender;
  }
  return "gender ?";
}

const GENDER_CYCLE: Array<string | null> = ["1girl", "1boy", "no_humans", null];

export function cycleGender(gender: string | null | undefined): string | null {
  const index = GENDER_CYCLE.indexOf(gender ?? null);
  const nextIndex = (index + 1) % GENDER_CYCLE.length;
  return GENDER_CYCLE[nextIndex];
}

export function resolveFinalPrompt(
  item: {
    character_tag: string;
    generation_prompt: string | null;
    multi_color_hair: string | null;
    hair_color: string | null;
    hair_shape: string | null;
    eye_color: string | null;
    feature_tags: string | null;
    gender: string | null;
  },
  draft: {
    enabledTags: Set<string>;
    customPrompt: string | null;
    promptEdited: boolean;
    promptCandidateMultiColorTags?: string[] | null;
  },
): string | null {
  if (draft.promptEdited && draft.customPrompt !== null) {
    return draft.customPrompt;
  }

  const chips = appearanceTagChips(item);
  const enabledTags =
    draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips, draft.promptCandidateMultiColorTags);
  return buildFinalPrompt(item.character_tag, item.generation_prompt, enabledTags, chips);
}
