from __future__ import annotations

from app.services.inspection_repair import (
    STAGE_AUTO_ZERO,
    STAGE_DONE,
    STAGE_IDENTITY_EYE,
    STAGE_IDENTITY_HAIR,
    STAGE_IDENTITY_MULTICOLOR,
    STAGE_SEMANTIC_GALLERY,
    STAGE_SEMANTIC_OUTFIT,
    RepairContext,
    decide_repair_stage,
)


def test_male_hair_then_auto_zero() -> None:
    ctx = RepairContext()
    assert (
        decide_repair_stage(
            gender="1boy",
            quality_status="pass",
            identity_status="warning",
            reasons=["hair_color_mismatch"],
            context=ctx,
        )
        == STAGE_IDENTITY_HAIR
    )
    ctx.mark(STAGE_IDENTITY_HAIR)
    assert (
        decide_repair_stage(
            gender="1boy",
            quality_status="pass",
            identity_status="warning",
            reasons=["hair_color_mismatch", "character_tag_low_confidence"],
            context=ctx,
        )
        == STAGE_AUTO_ZERO
    )


def test_male_low_confidence_without_hair_mismatch_does_not_invent_hair_repair() -> None:
    ctx = RepairContext()
    assert (
        decide_repair_stage(
            gender="1boy",
            quality_status="pass",
            identity_status="warning",
            reasons=["character_tag_low_confidence"],
            context=ctx,
        )
        == STAGE_AUTO_ZERO
    )


def test_female_hair_multicolor_eye_order() -> None:
    ctx = RepairContext()
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="warning",
            reasons=["hair_color_mismatch"],
            context=ctx,
        )
        == STAGE_IDENTITY_HAIR
    )
    ctx.mark(STAGE_IDENTITY_HAIR)
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="warning",
            reasons=["character_tag_low_confidence"],
            context=ctx,
        )
        == STAGE_IDENTITY_MULTICOLOR
    )
    ctx.mark(STAGE_IDENTITY_MULTICOLOR)
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="warning",
            reasons=["character_tag_low_confidence"],
            context=ctx,
        )
        == STAGE_IDENTITY_EYE
    )
    ctx.mark(STAGE_IDENTITY_EYE)
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="warning",
            reasons=["character_tag_low_confidence"],
            context=ctx,
        )
        == STAGE_AUTO_ZERO
    )


def test_character_tag_undetected_alone_does_not_regenerate_or_auto_zero() -> None:
    for gender, reason in (
        ("1girl", "character_tag_undetected"),
        ("1boy", "boy_character_tag_undetected"),
    ):
        ctx = RepairContext()
        assert (
            decide_repair_stage(
                gender=gender,
                quality_status="pass",
                identity_status="warning",
                reasons=[reason],
                context=ctx,
            )
            == STAGE_DONE
        )
        assert ctx.identity_ok is True


def test_actionable_identity_failure_skips_semantic_stages() -> None:
    ctx = RepairContext()
    ctx.mark(STAGE_IDENTITY_HAIR)
    ctx.mark(STAGE_IDENTITY_MULTICOLOR)
    ctx.mark(STAGE_IDENTITY_EYE)
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="reject",
            reasons=["character_tag_low_confidence", "atypical_swimwear:0.9/0.0"],
            context=ctx,
        )
        == STAGE_AUTO_ZERO
    )


def test_semantic_outfit_only_when_identity_ok() -> None:
    ctx = RepairContext()
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="reject",
            reasons=["atypical_swimwear:0.91/0.02"],
            context=ctx,
        )
        == STAGE_SEMANTIC_OUTFIT
    )


def test_semantic_gallery_only_when_identity_ok() -> None:
    ctx = RepairContext()
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="reject",
            reasons=["weak_print_gallery"],
            context=ctx,
        )
        == STAGE_SEMANTIC_GALLERY
    )


def test_multi_subject_output_uses_semantic_gallery_stage() -> None:
    ctx = RepairContext()
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="reject",
            reasons=["multi_subject_output:multiple_girls:0.48"],
            context=ctx,
        )
        == STAGE_SEMANTIC_GALLERY
    )


def test_tag_undetected_can_still_repair_semantic_gallery() -> None:
    ctx = RepairContext()
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="reject",
            reasons=["character_tag_undetected", "weak_print_gallery"],
            context=ctx,
        )
        == STAGE_SEMANTIC_GALLERY
    )


def test_female_undetected_tag_only_is_not_actionable() -> None:
    ctx = RepairContext()
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="warning",
            reasons=["character_tag_undetected"],
            context=ctx,
        )
        == STAGE_DONE
    )
    assert ctx.regeneration_requested == 0


def test_male_undetected_tag_only_is_not_actionable() -> None:
    ctx = RepairContext()
    assert (
        decide_repair_stage(
            gender="1boy",
            quality_status="pass",
            identity_status="warning",
            reasons=["boy_character_tag_undetected"],
            context=ctx,
        )
        == STAGE_DONE
    )


def test_undetected_tag_with_semantic_gallery_still_repairs_gallery() -> None:
    ctx = RepairContext()
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="reject",
            reasons=["character_tag_undetected", "weak_print_gallery"],
            context=ctx,
        )
        == STAGE_SEMANTIC_GALLERY
    )


def test_pass_returns_done() -> None:
    ctx = RepairContext()
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="pass",
            reasons=[],
            context=ctx,
        )
        == STAGE_DONE
    )
