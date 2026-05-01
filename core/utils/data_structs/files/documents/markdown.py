

import json
from collections.abc import Mapping
from typing import Any, ClassVar, Sequence

import yaml
from bs4 import BeautifulSoup

from ._structured import (
	PlainTextDoc,
	_MARKDOWN_HEADING_RE,
	_fallback_markdown_to_text,
	_json_default,
)
from ._utils import _normalize_multiline_text
from .base import LLMDocumentPart

try:
	import markdown as markdown_lib
except Exception:  # pragma: no cover
	markdown_lib = None  # type: ignore[assignment]


class Markdown(PlainTextDoc):
	'''Markdown 文档模型。'''

	Abstract: ClassVar[bool] = False
	Type: ClassVar[str] = 'markdown'
	TypeNames: ClassVar[tuple[str, ...]] = ('md', 'mdown')
	Suffixes: ClassVar[tuple[str, ...]] = ('.md', '.markdown', '.mdown')
	MimeTypes: ClassVar[tuple[str, ...]] = ('text/markdown',)

	def _split_front_matter(self) -> tuple[dict[str, Any], str]:
		text = self.to_text(normalize=False).lstrip('\ufeff')
		lines = text.splitlines()
		if not lines or lines[0].strip() != '---':
			return {}, self.to_text()

		end_index: int | None = None
		for index in range(1, len(lines)):
			if lines[index].strip() in {'---', '...'}:
				end_index = index
				break
		if end_index is None:
			return {}, self.to_text()

		front_matter_text = '\n'.join(lines[1:end_index]).strip()
		body = _normalize_multiline_text('\n'.join(lines[end_index + 1:]))
		parsed = yaml.safe_load(front_matter_text) if front_matter_text else {}
		if isinstance(parsed, Mapping):
			return dict(parsed), body
		if parsed is None:
			return {}, body
		return {'value': parsed}, body

	def front_matter(self) -> dict[str, Any]:
		return self._split_front_matter()[0]

	def body_markdown(self) -> str:
		return self._split_front_matter()[1]

	def heading_sections(self) -> list[dict[str, Any]]:
		body = self.body_markdown()
		matches = list(_MARKDOWN_HEADING_RE.finditer(body))
		if not matches:
			text = self.to_plain_text(include_front_matter=False)
			return [{'level': 1, 'title': 'Document', 'content': text}] if text else []

		sections: list[dict[str, Any]] = []
		for index, match in enumerate(matches):
			level = len(match.group(1))
			title = _normalize_multiline_text(match.group(2))
			start = match.end()
			end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
			raw_block = body[start:end].strip()
			content = self._markdown_fragment_to_text(raw_block)
			sections.append({'level': level, 'title': title, 'content': content})
		return sections

	def _markdown_fragment_to_text(self, text: str) -> str:
		text = text.strip()
		if not text:
			return ''
		if markdown_lib is not None:
			try:
				html = markdown_lib.markdown(text, extensions=['tables', 'fenced_code', 'nl2br'])
				return _normalize_multiline_text(BeautifulSoup(html, 'html.parser').get_text('\n'))
			except Exception:
				...
		return _fallback_markdown_to_text(text)

	def to_plain_text(self, *, include_front_matter: bool = False) -> str:
		metadata, body = self._split_front_matter()
		parts: list[str] = []
		if include_front_matter and metadata:
			parts.append(json.dumps(metadata, ensure_ascii=False, indent=2, default=_json_default))
		if body:
			parts.append(self._markdown_fragment_to_text(body))
		return _normalize_multiline_text('\n\n'.join(part for part in parts if part))

	async def to_llm(
		self,
		*,
		include_markup: bool = False,
		include_front_matter: bool = True,
		sectionized: bool = True,
		**kwargs: Any,
	) -> Sequence[LLMDocumentPart]:
		parts: list[LLMDocumentPart] = []
		metadata = self.front_matter()
		if include_front_matter and metadata:
			parts.append(
				'NOTE: Parsed Markdown front matter metadata.\n\n'
				+ json.dumps(metadata, ensure_ascii=False, indent=2, default=_json_default)
			)

		if sectionized:
			for section in self.heading_sections():
				title = str(section.get('title', '')).strip()
				content = str(section.get('content', '')).strip()
				heading = f"{'#' * max(1, min(int(section.get('level', 1) or 1), 6))} {title}".strip()
				block = '\n'.join(part for part in (heading if title else '', content) if part).strip()
				if block:
					parts.append(block)

		if not any(isinstance(part, str) and part.strip() for part in parts):
			plain_text = self.to_plain_text(include_front_matter=False)
			if plain_text:
				parts.append(plain_text)

		if include_markup:
			parts.append('NOTE: Original Markdown markup is attached below.')
			parts.append(self.to_text(normalize=False))
		return parts

__all__ = ['Markdown']
