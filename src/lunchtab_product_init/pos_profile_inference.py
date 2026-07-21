from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lunchtab_product_init.io import read_csv, write_csv
from lunchtab_product_init.models import LUNCHTAB_TEMPLATE_HEADERS
from lunchtab_product_init.naming import MAX_POS_NAME_LENGTH
from lunchtab_product_init.session_workflow import (
    ImportSession,
    PosNameAbbreviationPreference,
    PosNamePreferenceProfile,
    VenueProfile,
    learn_pos_preferences,
    load_venue_profile,
    merge_pos_preferences,
    save_venue_profile,
)
from lunchtab_product_init.workflow import default_output_root

PROPOSED_PROFILE_NAME = "Inferred Venue Profile Proposal.json"
INFERENCE_AUDIT_NAME = "POS Preference Inference Audit.csv"
PROPOSED_PROFILE_AUDIT_NAME = "Proposed POS Preference Profile.csv"


@dataclass(frozen=True)
class PosProfileInferencePaths:
    proposed_profile: Path
    inference_audit: Path
    proposed_profile_audit: Path
    manifest: Path
    summary: Path


@dataclass(frozen=True)
class PosProfileInferenceSummary:
    source_rows: int
    inferred_rows: int
    skipped_rows: int
    proposed_abbreviation_rules: int
    proposed_acronym_rules: int
    output_paths: PosProfileInferencePaths


@dataclass(frozen=True)
class PosProfileInferenceResult:
    run_dir: Path
    summary: PosProfileInferenceSummary
    inferred_preferences: PosNamePreferenceProfile
    proposed_preferences: PosNamePreferenceProfile


def infer_pos_profile_from_final_import(
    final_import_path: Path,
    *,
    existing_profile_path: Path | None = None,
    output_root: Path | None = None,
) -> PosProfileInferenceResult:
    headers, rows = read_csv(final_import_path)
    _require_final_import_headers(headers)
    existing_profile = load_venue_profile(existing_profile_path) if existing_profile_path else None
    inferred_preferences = PosNamePreferenceProfile(abbreviations={})
    learning_rows = []
    skipped_rows = []

    for index, row in enumerate(rows, start=1):
        item_name = _clean(row.get("BaseProductName", ""))
        pos_name = _clean(row.get("BaseProductPosName", ""))
        if not item_name or not pos_name:
            skipped_rows.append(_skip_row(index, item_name, pos_name, "missing name or POS name"))
            continue
        if len(pos_name) > MAX_POS_NAME_LENGTH:
            skipped_rows.append(
                _skip_row(index, item_name, pos_name, "POS name over 15 characters")
            )
            continue
        before = inferred_preferences
        inferred_preferences = learn_pos_preferences(inferred_preferences, item_name, pos_name)
        learning_rows.append(
            {
                "SourceRow": str(index),
                "BaseProductName": item_name,
                "BaseProductPosName": pos_name,
                "InferredAbbreviationRuleCountBefore": str(_abbreviation_rule_count(before)),
                "InferredAbbreviationRuleCountAfter": str(
                    _abbreviation_rule_count(inferred_preferences)
                ),
                "Skipped": "false",
                "SkipReason": "",
            }
        )

    existing_preferences = (
        existing_profile.pos_preferences
        if existing_profile is not None
        else PosNamePreferenceProfile(abbreviations={})
    )
    proposed_preferences = merge_pos_preferences(existing_preferences, inferred_preferences)
    run_dir = _run_dir(output_root)
    paths = PosProfileInferencePaths(
        proposed_profile=run_dir / PROPOSED_PROFILE_NAME,
        inference_audit=run_dir / INFERENCE_AUDIT_NAME,
        proposed_profile_audit=run_dir / PROPOSED_PROFILE_AUDIT_NAME,
        manifest=run_dir / "run-manifest.json",
        summary=run_dir / "run-summary.md",
    )
    categories = existing_profile.category_names if existing_profile is not None else ()
    profile_name = (
        f"{existing_profile.name} - POS Preference Proposal"
        if existing_profile is not None
        else "Inferred Venue POS Preference Proposal"
    )
    save_venue_profile(
        ImportSession(
            headers=list(LUNCHTAB_TEMPLATE_HEADERS),
            rows=(),
            category_names=categories,
            pos_preferences=proposed_preferences,
        ),
        paths.proposed_profile,
        name=profile_name,
    )
    write_csv(
        paths.inference_audit,
        _inference_audit_headers(),
        [
            *learning_rows,
            *skipped_rows,
            *_comparison_rows(existing_preferences, inferred_preferences, proposed_preferences),
        ],
    )
    write_csv(
        paths.proposed_profile_audit,
        _proposed_profile_audit_headers(),
        _proposed_profile_audit_rows(proposed_preferences),
    )
    summary = PosProfileInferenceSummary(
        source_rows=len(rows),
        inferred_rows=len(learning_rows),
        skipped_rows=len(skipped_rows),
        proposed_abbreviation_rules=_abbreviation_rule_count(proposed_preferences),
        proposed_acronym_rules=len(proposed_preferences.acronym_patterns),
        output_paths=paths,
    )
    _write_manifest(
        paths,
        summary,
        final_import_path=final_import_path,
        existing_profile_path=existing_profile_path,
    )
    _write_summary(paths.summary, summary, existing_profile=existing_profile)
    return PosProfileInferenceResult(
        run_dir=run_dir,
        summary=summary,
        inferred_preferences=inferred_preferences,
        proposed_preferences=proposed_preferences,
    )


def _require_final_import_headers(headers: list[str]) -> None:
    missing = [name for name in ("BaseProductName", "BaseProductPosName") if name not in headers]
    if missing:
        raise ValueError(f"Final import CSV is missing required headers: {', '.join(missing)}")


def _run_dir(output_root: Path | None) -> Path:
    root = output_root or default_output_root() / "POS Profile Inference"
    return root / datetime.now().strftime("%Y-%m-%d_%H%M%S")


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


def _skip_row(index: int, item_name: str, pos_name: str, reason: str) -> dict[str, str]:
    return {
        "SourceRow": str(index),
        "BaseProductName": item_name,
        "BaseProductPosName": pos_name,
        "InferredAbbreviationRuleCountBefore": "",
        "InferredAbbreviationRuleCountAfter": "",
        "Skipped": "true",
        "SkipReason": reason,
    }


def _inference_audit_headers() -> list[str]:
    return [
        "SourceRow",
        "BaseProductName",
        "BaseProductPosName",
        "InferredAbbreviationRuleCountBefore",
        "InferredAbbreviationRuleCountAfter",
        "Skipped",
        "SkipReason",
        "RuleType",
        "Token",
        "Replacement",
        "ExistingCount",
        "InferredCount",
        "ProposedCount",
        "ExistingRank",
        "InferredRank",
        "ProposedRank",
        "ExistingTopReplacement",
        "InferredTopReplacement",
        "ProposedTopReplacement",
        "ReviewRecommended",
        "Action",
        "Examples",
    ]


def _comparison_rows(
    existing: PosNamePreferenceProfile,
    inferred: PosNamePreferenceProfile,
    proposed: PosNamePreferenceProfile,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    existing_options = _option_index(existing)
    inferred_options = _option_index(inferred)
    proposed_options = _option_index(proposed)
    for key in sorted(set(existing_options) | set(inferred_options) | set(proposed_options)):
        existing_option = existing_options.get(key)
        inferred_option = inferred_options.get(key)
        proposed_option = proposed_options.get(key)
        token, replacement = key
        token_has_existing = token in existing.abbreviation_options
        token_has_inferred = token in inferred.abbreviation_options
        rows.append(
            {
                "SourceRow": "",
                "BaseProductName": "",
                "BaseProductPosName": "",
                "InferredAbbreviationRuleCountBefore": "",
                "InferredAbbreviationRuleCountAfter": "",
                "Skipped": "",
                "SkipReason": "",
                "RuleType": "abbreviation",
                "Token": token,
                "Replacement": replacement,
                "ExistingCount": _count(existing_option),
                "InferredCount": _count(inferred_option),
                "ProposedCount": _count(proposed_option),
                "ExistingRank": _rank(existing_option),
                "InferredRank": _rank(inferred_option),
                "ProposedRank": _rank(proposed_option),
                "ExistingTopReplacement": _top_replacement(existing, token),
                "InferredTopReplacement": _top_replacement(inferred, token),
                "ProposedTopReplacement": _top_replacement(proposed, token),
                "ReviewRecommended": _review_recommended(
                    existing, inferred, proposed, token, replacement
                ),
                "Action": _action(
                    existing_option,
                    inferred_option,
                    token_has_existing=token_has_existing,
                    token_has_inferred=token_has_inferred,
                ),
                "Examples": " | ".join(
                    dict.fromkeys(
                        (
                            *(existing_option[0].examples if existing_option else ()),
                            *(inferred_option[0].examples if inferred_option else ()),
                        )
                    )
                ),
            }
        )
    for index, pattern in enumerate(proposed.acronym_patterns, start=1):
        rows.append(
            {
                "SourceRow": "",
                "BaseProductName": "",
                "BaseProductPosName": "",
                "InferredAbbreviationRuleCountBefore": "",
                "InferredAbbreviationRuleCountAfter": "",
                "Skipped": "",
                "SkipReason": "",
                "RuleType": "acronym",
                "Token": ", ".join(pattern.suffix_tokens),
                "Replacement": f"first {pattern.span_length} initials",
                "ExistingCount": "",
                "InferredCount": "",
                "ProposedCount": str(pattern.count),
                "ExistingRank": "",
                "InferredRank": "",
                "ProposedRank": str(index),
                "ExistingTopReplacement": "",
                "InferredTopReplacement": "",
                "ProposedTopReplacement": "",
                "ReviewRecommended": "",
                "Action": "proposed",
                "Examples": " | ".join(pattern.examples),
            }
        )
    return rows


def _option_index(
    profile: PosNamePreferenceProfile,
) -> dict[tuple[str, str], tuple[PosNameAbbreviationPreference, int]]:
    indexed = {}
    for token, options in profile.abbreviation_options.items():
        for rank, option in enumerate(options, start=1):
            indexed[(token, option.value.casefold())] = (option, rank)
    return indexed


def _count(option: tuple[PosNameAbbreviationPreference, int] | None) -> str:
    if option is None:
        return ""
    return str(option[0].count)


def _rank(option: tuple[PosNameAbbreviationPreference, int] | None) -> str:
    if option is None:
        return ""
    return str(option[1])


def _top_replacement(profile: PosNamePreferenceProfile, token: str) -> str:
    options = profile.abbreviation_options.get(token, ())
    if not options:
        return ""
    return options[0].value


def _review_recommended(
    existing: PosNamePreferenceProfile,
    inferred: PosNamePreferenceProfile,
    proposed: PosNamePreferenceProfile,
    token: str,
    replacement: str,
) -> str:
    existing_top = _top_replacement(existing, token).casefold()
    inferred_top = _top_replacement(inferred, token).casefold()
    proposed_top = _top_replacement(proposed, token).casefold()
    if existing_top and inferred_top and existing_top != inferred_top:
        return "true"
    if replacement == proposed_top and existing_top and proposed_top != existing_top:
        return "true"
    return "false"


def _action(
    existing_option: tuple[PosNameAbbreviationPreference, int] | None,
    inferred_option: tuple[PosNameAbbreviationPreference, int] | None,
    *,
    token_has_existing: bool,
    token_has_inferred: bool,
) -> str:
    if existing_option is None and inferred_option is not None:
        if token_has_existing:
            return "new competing rule"
        return "new inferred rule"
    if existing_option is not None and inferred_option is not None:
        return "reinforced existing rule"
    if existing_option is not None and token_has_inferred:
        return "existing competing rule"
    return "existing only"


def _abbreviation_rule_count(profile: PosNamePreferenceProfile) -> int:
    return sum(len(options) for options in profile.abbreviation_options.values())


def _proposed_profile_audit_headers() -> list[str]:
    return [
        "RuleType",
        "Token",
        "Rank",
        "Replacement",
        "Count",
        "SourceTokenCounts",
        "OverrideLengths",
        "SuffixTokens",
        "SpanLength",
        "Examples",
        "SpacedOverrides",
        "CompactOverrides",
    ]


def _proposed_profile_audit_rows(profile: PosNamePreferenceProfile):
    for token, options in sorted(profile.abbreviation_options.items()):
        for rank, option in enumerate(options, start=1):
            yield {
                "RuleType": "abbreviation",
                "Token": token,
                "Rank": str(rank),
                "Replacement": option.value,
                "Count": str(option.count),
                "SourceTokenCounts": _join_ints(option.source_token_counts),
                "OverrideLengths": _join_ints(option.override_lengths),
                "SuffixTokens": "",
                "SpanLength": "",
                "Examples": " | ".join(option.examples),
                "SpacedOverrides": "",
                "CompactOverrides": "",
            }
    for rank, pattern in enumerate(profile.acronym_patterns, start=1):
        yield {
            "RuleType": "acronym",
            "Token": "",
            "Rank": str(rank),
            "Replacement": "",
            "Count": str(pattern.count),
            "SourceTokenCounts": "",
            "OverrideLengths": "",
            "SuffixTokens": ", ".join(pattern.suffix_tokens),
            "SpanLength": str(pattern.span_length),
            "Examples": " | ".join(pattern.examples),
            "SpacedOverrides": "",
            "CompactOverrides": "",
        }
    yield {
        "RuleType": "style",
        "Token": "",
        "Rank": "",
        "Replacement": "",
        "Count": "",
        "SourceTokenCounts": "",
        "OverrideLengths": "",
        "SuffixTokens": "",
        "SpanLength": "",
        "Examples": "",
        "SpacedOverrides": str(profile.spaced_overrides),
        "CompactOverrides": str(profile.compact_overrides),
    }


def _join_ints(values: tuple[int, ...]) -> str:
    return ", ".join(str(value) for value in values)


def _write_manifest(
    paths: PosProfileInferencePaths,
    summary: PosProfileInferenceSummary,
    *,
    final_import_path: Path,
    existing_profile_path: Path | None,
) -> None:
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "final_import_csv": {"filename": final_import_path.name},
            "existing_profile": {"filename": existing_profile_path.name}
            if existing_profile_path is not None
            else None,
        },
        "counts": {
            "source_rows": summary.source_rows,
            "inferred_rows": summary.inferred_rows,
            "skipped_rows": summary.skipped_rows,
            "proposed_abbreviation_rules": summary.proposed_abbreviation_rules,
            "proposed_acronym_rules": summary.proposed_acronym_rules,
        },
        "artifacts": {
            "proposed_profile": paths.proposed_profile.name,
            "inference_audit": paths.inference_audit.name,
            "proposed_profile_audit": paths.proposed_profile_audit.name,
            "summary": paths.summary.name,
        },
    }
    paths.manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_summary(
    path: Path,
    summary: PosProfileInferenceSummary,
    *,
    existing_profile: VenueProfile | None,
) -> None:
    lines = [
        "# POS Preference Profile Inference",
        "",
        f"- Source rows scanned: {summary.source_rows}",
        f"- Rows used for inference: {summary.inferred_rows}",
        f"- Rows skipped: {summary.skipped_rows}",
        f"- Proposed abbreviation rules: {summary.proposed_abbreviation_rules}",
        f"- Proposed acronym rules: {summary.proposed_acronym_rules}",
        f"- Existing profile: {existing_profile.name if existing_profile else 'none'}",
        "",
        "Review the proposed profile and audit before replacing an active venue profile.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Infer Lunchtab POS-name venue profile preferences from a final import CSV."
    )
    parser.add_argument("final_import_csv", nargs="?", type=Path)
    parser.add_argument("--profile", type=Path, help="Existing venue profile JSON to merge into.")
    parser.add_argument("--output-root", type=Path, help="Directory for inference artifacts.")
    parser.add_argument("--smoke-test", action="store_true", help="Verify the command imports.")
    args = parser.parse_args(argv)
    if args.smoke_test:
        print("lt-pos-profile-infer smoke ok")
        return 0
    if args.final_import_csv is None:
        parser.error("final_import_csv is required unless --smoke-test is used")
    result = infer_pos_profile_from_final_import(
        args.final_import_csv,
        existing_profile_path=args.profile,
        output_root=args.output_root,
    )
    print(f"Wrote POS profile inference artifacts: {result.run_dir}")
    print(f"Proposed profile: {result.summary.output_paths.proposed_profile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
