"""
Config-driven template engine for the IMBUTO ingestion pipeline.

:class:`TemplateManager` loads YAML templates from a configurable
directory and transforms user form inputs into the standard ingestion
schema consumed by :class:`VaultManager`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

import yaml

from personal_os.core.logger import get_logger

logger: logging.Logger = get_logger("imbuto.template")


class TemplateManager:
    """YAML-backed template registry and renderer.

    Args:
        template_dir: Path to the directory containing ``.yml``
            template files.  Created automatically if absent.

    Example::

        tm = TemplateManager()
        templates = tm.list_templates()
        schema = tm.render_to_schema(templates["software_design.yml"], user_inputs)
    """

    def __init__(self, template_dir: str = "data/templates") -> None:
        from personal_os.path_resolver import get_resource_path
        self._dir: Path = get_resource_path(template_dir).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.info("TemplateManager initialised — dir: %s", self._dir)

    # -- listing -----------------------------------------------------------

    def list_templates(self) -> Dict[str, Dict[str, Any]]:
        """Parse all ``.yml`` files in the template directory.

        Returns:
            Mapping of ``{filename: parsed_yaml_dict}``.
            Files that fail to parse are logged and skipped.
        """
        templates: Dict[str, Dict[str, Any]] = {}

        for entry in sorted(self._dir.iterdir()):
            if entry.suffix not in (".yml", ".yaml"):
                continue
            try:
                with entry.open("r", encoding="utf-8") as fh:
                    data: Dict[str, Any] = yaml.safe_load(fh) or {}
                templates[entry.name] = data
                logger.debug("Loaded template: %s", entry.name)
            except (yaml.YAMLError, OSError) as exc:
                logger.warning(
                    "Skipping invalid template %s: %s", entry.name, exc
                )

        logger.info("Found %d template(s).", len(templates))
        return templates

    # -- rendering ---------------------------------------------------------

    def render_to_schema(
        self,
        template_config: Dict[str, Any],
        user_inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Transform user form inputs into the standard ingestion schema.

        Iterates over the template's ``fields`` list to build a
        structured Markdown body (``normalized_content``) and extracts
        tags from any ``list``-type fields.

        Args:
            template_config: Parsed YAML template dictionary.
            user_inputs: Key-value mapping of user-supplied field values.

        Returns:
            Dictionary compatible with :meth:`VaultManager.save_note`::

                {
                    "title": "...",
                    "flag": "...",
                    "tags": [...],
                    "summary": "...",
                    "normalized_content": "...",
                    "confidence_score": 1.0,
                }
        """
        fields: List[Dict[str, Any]] = template_config.get("fields", [])

        # Build normalised Markdown body.
        md_parts: List[str] = []
        tags: List[str] = []

        for field in fields:
            name: str = field.get("name", "")
            label: str = field.get("label", name)
            field_type: str = field.get("type", "string")
            value: Any = user_inputs.get(name, "")

            md_parts.append(f"# {label}\n{value}\n")

            # Collect tags from list-type fields.
            if field_type == "list" and isinstance(value, str):
                parsed_tags: List[str] = [
                    t.strip().lower().replace(" ", "-")
                    for t in value.split(",")
                    if t.strip()
                ]
                tags.extend(parsed_tags)

        normalized_content: str = "\n".join(md_parts)

        title: str = user_inputs.get("project_name", "Untitled Document")
        flag: str = template_config.get("flag", "research")
        template_name: str = template_config.get("name", "Unknown")
        summary: str = (
            f"Structured document generated from {template_name} template."
        )

        return {
            "title": title,
            "flag": flag,
            "tags": tags,
            "summary": summary,
            "normalized_content": normalized_content,
            "confidence_score": 1.0,
        }
