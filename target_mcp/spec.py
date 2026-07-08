"""Spec layer: versioned, validated access to the encoded TARGET checklist."""

from __future__ import annotations

import functools
from importlib import resources
from typing import Any

import yaml

EXPECTED_LEAF_COUNT = 39
EXPECTED_ITEM_COUNT = 21
DEFAULT_VERSION = "target-0.1.0"

SECTIONS = ("abstract", "introduction", "methods", "results", "discussion", "other")
VERDICTS = ("reported", "partial", "not_reported", "not_applicable")


class SpecError(ValueError):
    pass


def available_versions() -> list[str]:
    files = resources.files("target_mcp.specs")
    return sorted(
        p.name.removesuffix(".yaml")
        for p in files.iterdir()
        if p.name.endswith(".yaml")
    )


@functools.lru_cache(maxsize=8)
def load_spec(version: str = DEFAULT_VERSION) -> dict[str, Any]:
    """Load and structurally validate a spec version."""
    ref = resources.files("target_mcp.specs").joinpath(f"{version}.yaml")
    try:
        raw = ref.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SpecError(
            f"Unknown spec version {version!r}. Available: {available_versions()}"
        ) from None
    spec = yaml.safe_load(raw)
    _validate(spec)
    return spec


def _validate(spec: dict[str, Any]) -> None:
    items = spec.get("items", [])
    ids = [it["id"] for it in items]
    if len(ids) != len(set(ids)):
        raise SpecError("Duplicate leaf ids in spec")
    if len(items) != EXPECTED_LEAF_COUNT:
        raise SpecError(f"Expected {EXPECTED_LEAF_COUNT} leaves, found {len(items)}")
    item_nos = {it["item_no"] for it in items}
    if item_nos != set(range(1, EXPECTED_ITEM_COUNT + 1)):
        raise SpecError(f"Expected item_no 1..{EXPECTED_ITEM_COUNT}, found {sorted(item_nos)}")

    by_id = {it["id"]: it for it in items}
    for it in items:
        if it["section"] not in SECTIONS:
            raise SpecError(f"Leaf {it['id']}: bad section {it['section']!r}")
        for pid in it.get("paired_with", []):
            if pid not in by_id:
                raise SpecError(f"Leaf {it['id']}: pairs with unknown leaf {pid!r}")
            if it["id"] not in by_id[pid].get("paired_with", []):
                raise SpecError(f"Pairing not symmetric: {it['id']} -> {pid}")
        if it.get("applicability") == "conditional" and not it.get("applicability_rule"):
            raise SpecError(f"Leaf {it['id']}: conditional without applicability_rule")

    floor = set(spec["critical_floor"]["leaves"])
    flagged = {it["id"] for it in items if it.get("critical_floor")}
    if floor != flagged:
        raise SpecError(
            f"critical_floor.leaves {sorted(floor)} != leaves flagged critical_floor {sorted(flagged)}"
        )


def get_leaf(leaf_id: str, version: str = DEFAULT_VERSION) -> dict[str, Any]:
    spec = load_spec(version)
    for it in spec["items"]:
        if it["id"] == leaf_id:
            return it
    raise SpecError(f"Unknown leaf id {leaf_id!r} in {version}")


def floor_leaves(version: str = DEFAULT_VERSION) -> list[str]:
    return list(load_spec(version)["critical_floor"]["leaves"])
