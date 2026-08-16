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
            identity_status="reject",
            reasons=["character_tag_undetected"],
            context=ctx,
        )
        == STAGE_IDENTITY_EYE
    )
    ctx.mark(STAGE_IDENTITY_EYE)
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="reject",
            reasons=["character_tag_undetected"],
            context=ctx,
        )
        == STAGE_AUTO_ZERO
    )


def test_identity_failure_skips_semantic_stages() -> None:
    ctx = RepairContext()
    ctx.mark(STAGE_IDENTITY_HAIR)
    ctx.mark(STAGE_IDENTITY_MULTICOLOR)
    ctx.mark(STAGE_IDENTITY_EYE)
    assert (
        decide_repair_stage(
            gender="1girl",
            quality_status="pass",
            identity_status="reject",
            reasons=["character_tag_undetected", "atypical_swimwear:0.9/0.0"],
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
