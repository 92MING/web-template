

from typing import Any, ClassVar

import yaml

from ._structured import DictLikedDocument


class YAML(DictLikedDocument):
	'''YAML 文档模型。'''

	Abstract: ClassVar[bool] = False
	Type: ClassVar[str] = 'yaml'
	TypeNames: ClassVar[tuple[str, ...]] = ('yml',)
	Suffixes: ClassVar[tuple[str, ...]] = ('.yaml', '.yml')
	MimeTypes: ClassVar[tuple[str, ...]] = ('application/yaml', 'text/yaml')

	def _parse_data(self) -> Any:
		return yaml.safe_load(self.to_text(normalize=False))

__all__ = ['YAML']
