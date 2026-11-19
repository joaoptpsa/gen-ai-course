"""Assign every case to the train, valid or test side of the improvement loop and fingerprint them.

The assignment lives in app/case-splits.yaml. load_splits refuses to return anything unless every
case has exactly one side, has its check, and no ext- family is spread over two sides.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.core.catalog import CaseInfo

SPLITS_FILE = Path(__file__).resolve().parents[1] / "case-splits.yaml"
SPLIT_NAMES: tuple[Literal["train", "valid", "test"], ...] = ("train", "valid", "test")
# Generated cases are only ever admitted to train, so a held-out case cannot be drafted into it.
TRAIN_ONLY_PREFIXES = ("train-coordination-",)


class SplitError(ValueError):
    """The cases and case-splits.yaml disagree; the message lists every problem found."""


class SplitRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: list[str] = Field(default_factory=list)
    prefixes: list[str] = Field(default_factory=list)
    families: dict[str, list[str]] = Field(default_factory=dict)


class SplitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    train: SplitRule
    valid: SplitRule
    test: SplitRule


class CaseSplits(BaseModel):
    model_config = ConfigDict(frozen=True)

    train: list[str]
    valid: list[str]
    test: list[str]
    # Hash of the case and check file contents of each split, in case id order.
    fingerprints: dict[str, str]

    @property
    def fingerprint(self) -> str:
        parts = [f"{name}={self.fingerprints[name]}" for name in SPLIT_NAMES]
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    def split_of(self, case_id: str) -> str | None:
        for name in SPLIT_NAMES:
            if case_id in getattr(self, name):
                return name
        return None


def _read_config(path: Path) -> SplitConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SplitConfig.model_validate(data)


def _config_problems(config: SplitConfig) -> list[str]:
    problems: list[str] = []
    family_sides: dict[str, str] = {}
    for name in SPLIT_NAMES:
        rule: SplitRule = getattr(config, name)
        for family in rule.families:
            other = family_sides.setdefault(family, name)
            if other != name:
                problems.append(f"family {family!r} is split across {other} and {name}")
        if name == "train":
            continue
        for prefix in rule.prefixes:
            problems.append(f"{name} lists the train-only prefix {prefix!r}")
    for prefix in TRAIN_ONLY_PREFIXES:
        if prefix not in config.train.prefixes:
            problems.append(f"train does not reserve the prefix {prefix!r}")
    return problems


def _sides_of(case: CaseInfo, config: SplitConfig) -> list[str]:
    sides: list[str] = []
    for name in SPLIT_NAMES:
        rule: SplitRule = getattr(config, name)
        listed = [case_id for ids in rule.families.values() for case_id in ids]
        by_session = case.session in rule.sessions
        by_prefix = case.case_id.startswith(tuple(rule.prefixes))
        sides.extend([name] * (listed.count(case.case_id) + by_session + by_prefix))
    return sides


def _reserved_prefix_problem(case: CaseInfo, sides: list[str]) -> str | None:
    if not case.case_id.startswith(TRAIN_ONLY_PREFIXES):
        return None
    if sides == ["train"]:
        return None
    return f"{case.case_id}: reserved prefix is admitted to train only, found {sides}"


def _fingerprint(cases: Sequence[CaseInfo]) -> str:
    digest = hashlib.sha256()
    for case in sorted(cases, key=lambda item: item.case_id):
        digest.update(case.case_id.encode())
        digest.update(case.path.read_bytes())
        if case.check_path is not None:
            digest.update(case.check_path.read_bytes())
    return digest.hexdigest()


def _unknown_ids(config: SplitConfig, known: set[str]) -> list[str]:
    problems: list[str] = []
    for name in SPLIT_NAMES:
        rule: SplitRule = getattr(config, name)
        for ids in rule.families.values():
            problems.extend(
                f"{name} lists unknown case {case_id!r}"
                for case_id in ids
                if case_id not in known
            )
    return problems


def load_splits(
    cases: Sequence[CaseInfo], *, splits_file: Path = SPLITS_FILE
) -> CaseSplits:
    config = _read_config(splits_file)
    problems = _config_problems(config)
    problems.extend(_unknown_ids(config, {case.case_id for case in cases}))
    members: dict[str, list[CaseInfo]] = {name: [] for name in SPLIT_NAMES}
    for case in cases:
        sides = _sides_of(case, config)
        if case.check_path is None:
            problems.append(f"{case.case_id}: missing its check file")
        if not sides:
            problems.append(f"{case.case_id}: not assigned to any split")
        if len(sides) > 1:
            problems.append(f"{case.case_id}: assigned more than once ({sides})")
        reserved = _reserved_prefix_problem(case, sides)
        if reserved:
            problems.append(reserved)
        if len(sides) == 1:
            members[sides[0]].append(case)
    if problems:
        raise SplitError("; ".join(problems))
    ids = {name: sorted(case.case_id for case in members[name]) for name in SPLIT_NAMES}
    fingerprints = {name: _fingerprint(members[name]) for name in SPLIT_NAMES}
    return CaseSplits(
        train=ids["train"],
        valid=ids["valid"],
        test=ids["test"],
        fingerprints=fingerprints,
    )
