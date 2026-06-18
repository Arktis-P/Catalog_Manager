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
]);

function tagToPromptText(tag: string): string {
  return tag.trim().replace(/_/g, " ");
}

function characterTagToPromptName(characterTag: string): string {
  return characterTag.trim().replace(/_/g, " ");
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
}): Array<{ key: string; label: string; group: "gender" | "hair" | "multi" | "shape" | "eyes" | "features" }> {
  const chips: Array<{ key: string; label: string; group: "gender" | "hair" | "multi" | "shape" | "eyes" | "features" }> = [];

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

  return chips;
}

export function buildFinalPrompt(
  characterTag: string,
  basePrompt: string | null,
  enabledTagKeys: Set<string>,
  chips: ReturnType<typeof appearanceTagChips>,
): string | null {
  if (!basePrompt) {
    return null;
  }

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
    return basePrompt;
  }

  const name = characterTagToPromptName(characterTag);
  return `{{${name}, [[${innerParts.join(", ")}]]}}`;
}

export function defaultEnabledTagKeys(chips: ReturnType<typeof appearanceTagChips>): Set<string> {
  const enabled = new Set<string>();
  let primaryHairEnabled = false;

  for (const chip of chips) {
    if (chip.group === "hair") {
      if (!primaryHairEnabled) {
        enabled.add(chip.key);
        primaryHairEnabled = true;
      }
      continue;
    }
    if (chip.group === "multi") {
      enabled.add(chip.key);
    }
  }

  return enabled;
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
  return "review-tag";
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
  },
): string | null {
  if (draft.promptEdited && draft.customPrompt !== null) {
    return draft.customPrompt;
  }

  const chips = appearanceTagChips(item);
  const enabledTags = draft.enabledTags.size > 0 ? draft.enabledTags : defaultEnabledTagKeys(chips);
  return buildFinalPrompt(item.character_tag, item.generation_prompt, enabledTags, chips);
}

