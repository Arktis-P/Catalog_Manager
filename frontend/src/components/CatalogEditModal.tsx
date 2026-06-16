import { FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import type { CatalogItem, CatalogItemUpdatePayload } from "../types";

interface CatalogEditModalProps {
  item: CatalogItem;
  onClose: () => void;
  onSaved: (item: CatalogItem) => void;
}

const GENDER_OPTIONS = ["", "1girl", "1boy", "no_humans"] as const;

export function CatalogEditModal({ item, onClose, onSaved }: CatalogEditModalProps) {
  const [multiColorHair, setMultiColorHair] = useState(item.multi_color_hair ?? "");
  const [hairColor, setHairColor] = useState(item.hair_color ?? "");
  const [hairShape, setHairShape] = useState(item.hair_shape ?? "");
  const [eyeColor, setEyeColor] = useState(item.eye_color ?? "");
  const [featureTags, setFeatureTags] = useState(item.feature_tags ?? "");
  const [gender, setGender] = useState(item.gender ?? "");
  const [rating, setRating] = useState(item.rating !== null ? String(item.rating) : "");
  const [type, setType] = useState(item.type ?? "");
  const [finalPrompt, setFinalPrompt] = useState(item.final_prompt ?? item.generation_prompt ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setMultiColorHair(item.multi_color_hair ?? "");
    setHairColor(item.hair_color ?? "");
    setHairShape(item.hair_shape ?? "");
    setEyeColor(item.eye_color ?? "");
    setFeatureTags(item.feature_tags ?? "");
    setGender(item.gender ?? "");
    setRating(item.rating !== null ? String(item.rating) : "");
    setType(item.type ?? "");
    setFinalPrompt(item.final_prompt ?? item.generation_prompt ?? "");
  }, [item]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const payload: CatalogItemUpdatePayload = {
      multi_color_hair: multiColorHair || null,
      hair_color: hairColor || null,
      hair_shape: hairShape || null,
      eye_color: eyeColor || null,
      feature_tags: featureTags || null,
      gender: gender || null,
      type: type || null,
      final_prompt: finalPrompt || null,
    };
    if (rating !== "") {
      payload.rating = Number(rating);
    }
    try {
      const updated = await api.updateCatalogItem(item.id, payload);
      onSaved(updated);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save catalog item");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={(event) => event.stopPropagation()}>
        <h2 className="modal-title">Edit — {item.character_tag}</h2>
        <p className="page-description">
          {item.series_tag} · appearance 태그 변경 시 generation prompt가 자동 재생성됩니다.
        </p>
        {error ? <div className="error-banner">{error}</div> : null}
        <form onSubmit={(event) => void handleSubmit(event)}>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="edit-hair-color">hair_color</label>
              <input id="edit-hair-color" value={hairColor} onChange={(event) => setHairColor(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="edit-multi-color-hair">multi_color_hair</label>
              <input
                id="edit-multi-color-hair"
                value={multiColorHair}
                onChange={(event) => setMultiColorHair(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="edit-hair-shape">hair_shape</label>
              <input id="edit-hair-shape" value={hairShape} onChange={(event) => setHairShape(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="edit-eye-color">eye_color</label>
              <input id="edit-eye-color" value={eyeColor} onChange={(event) => setEyeColor(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="edit-feature-tags">feature_tags</label>
              <input
                id="edit-feature-tags"
                value={featureTags}
                onChange={(event) => setFeatureTags(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="edit-gender">gender</label>
              <select id="edit-gender" value={gender} onChange={(event) => setGender(event.target.value)}>
                {GENDER_OPTIONS.map((option) => (
                  <option key={option || "empty"} value={option}>
                    {option || "(none)"}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="edit-rating">rating</label>
              <select id="edit-rating" value={rating} onChange={(event) => setRating(event.target.value)}>
                <option value="">(none)</option>
                <option value="-1">-1</option>
                {Array.from({ length: 7 }, (_, index) => (
                  <option key={index} value={String(index)}>
                    {index}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="edit-type">type</label>
              <input id="edit-type" value={type} onChange={(event) => setType(event.target.value)} />
            </div>
            <div className="field full-width">
              <label htmlFor="edit-generation-prompt">generation_prompt (read-only)</label>
              <textarea
                id="edit-generation-prompt"
                className="generation-prompt-textarea"
                rows={3}
                value={item.generation_prompt ?? ""}
                readOnly
              />
            </div>
            <div className="field full-width">
              <label htmlFor="edit-final-prompt">final_prompt</label>
              <textarea
                id="edit-final-prompt"
                className="generation-prompt-textarea"
                rows={4}
                value={finalPrompt}
                onChange={(event) => setFinalPrompt(event.target.value)}
              />
            </div>
          </div>
          <div className="modal-actions">
            <button className="btn" type="button" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" type="submit" disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
