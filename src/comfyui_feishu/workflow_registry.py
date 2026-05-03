from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class WorkflowConfigError(ValueError):
    pass


@dataclass(frozen=True)
class NodeInputRef:
    node_id: str
    input_name: str
    default: Any = None
    randomize: bool = False


@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    name: str
    description: str
    file: str
    positive_prompt: NodeInputRef
    negative_prompt: NodeInputRef | None = None
    seed: NodeInputRef | None = None
    width: NodeInputRef | None = None
    height: NodeInputRef | None = None


@dataclass(frozen=True)
class Workflow:
    spec: WorkflowSpec
    prompt: dict[str, Any]

    def build_prompt(self, positive_prompt: str) -> dict[str, Any]:
        prompt = copy.deepcopy(self.prompt)
        _set_node_input(prompt, self.spec.positive_prompt, positive_prompt)

        optional_refs = [self.spec.negative_prompt, self.spec.width, self.spec.height]
        for ref in optional_refs:
            if ref is not None and ref.default is not None:
                _set_node_input(prompt, ref, ref.default)

        if self.spec.seed is not None:
            seed_value = random.randint(1, 2**63 - 1) if self.spec.seed.randomize else self.spec.seed.default
            if seed_value is not None:
                _set_node_input(prompt, self.spec.seed, seed_value)

        return prompt


class WorkflowRegistry:
    def __init__(self, workflows: dict[str, Workflow]) -> None:
        self._workflows = workflows

    @classmethod
    def load(cls, workflow_dir: Path) -> "WorkflowRegistry":
        index_path = workflow_dir / "index.yaml"
        if not index_path.exists():
            raise WorkflowConfigError(f"workflow index not found: {index_path}")

        raw_index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
        specs = raw_index.get("workflows")
        if not isinstance(specs, list) or not specs:
            raise WorkflowConfigError("workflows/index.yaml must contain a non-empty workflows list")

        workflows: dict[str, Workflow] = {}
        for item in specs:
            spec = _parse_workflow_spec(item)
            if spec.id in workflows:
                raise WorkflowConfigError(f"duplicate workflow id: {spec.id}")

            workflow_path = workflow_dir / spec.file
            if not workflow_path.exists():
                raise WorkflowConfigError(f"workflow file not found for {spec.id}: {workflow_path}")

            prompt = json.loads(workflow_path.read_text(encoding="utf-8"))
            _validate_prompt(spec, prompt)
            workflows[spec.id] = Workflow(spec=spec, prompt=prompt)

        return cls(workflows)

    def list(self) -> list[WorkflowSpec]:
        return [workflow.spec for workflow in self._workflows.values()]

    def get(self, workflow_id: str) -> Workflow:
        try:
            return self._workflows[workflow_id]
        except KeyError as exc:
            raise WorkflowConfigError(f"unknown workflow id: {workflow_id}") from exc


def _parse_workflow_spec(item: dict[str, Any]) -> WorkflowSpec:
    try:
        return WorkflowSpec(
            id=str(item["id"]),
            name=str(item.get("name") or item["id"]),
            description=str(item.get("description") or ""),
            file=str(item["file"]),
            positive_prompt=_parse_ref(item["positive_prompt"]),
            negative_prompt=_parse_ref(item.get("negative_prompt")),
            seed=_parse_ref(item.get("seed")),
            width=_parse_ref(item.get("width")),
            height=_parse_ref(item.get("height")),
        )
    except KeyError as exc:
        raise WorkflowConfigError(f"missing workflow config field: {exc}") from exc


def _parse_ref(raw: dict[str, Any] | None) -> NodeInputRef | None:
    if raw is None:
        return None
    if "node_id" not in raw or "input" not in raw:
        raise WorkflowConfigError("node input ref must include node_id and input")
    return NodeInputRef(
        node_id=str(raw["node_id"]),
        input_name=str(raw["input"]),
        default=raw.get("default"),
        randomize=bool(raw.get("randomize", False)),
    )


def _validate_prompt(spec: WorkflowSpec, prompt: dict[str, Any]) -> None:
    refs = [spec.positive_prompt, spec.negative_prompt, spec.seed, spec.width, spec.height]
    for ref in refs:
        if ref is None:
            continue
        node = prompt.get(ref.node_id)
        if not isinstance(node, dict):
            raise WorkflowConfigError(f"{spec.id}: node {ref.node_id} not found")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise WorkflowConfigError(f"{spec.id}: node {ref.node_id} has no inputs")
        if ref.input_name not in inputs:
            raise WorkflowConfigError(f"{spec.id}: node {ref.node_id} input {ref.input_name} not found")


def _set_node_input(prompt: dict[str, Any], ref: NodeInputRef, value: Any) -> None:
    prompt[ref.node_id]["inputs"][ref.input_name] = value
