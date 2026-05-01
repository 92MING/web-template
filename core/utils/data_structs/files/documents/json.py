

from typing import Any, ClassVar

import json5

from ._structured import DictLikedDocument


class JSON(DictLikedDocument):
	'''JSON/JSON5 文档模型。'''

	Abstract: ClassVar[bool] = False
	Type: ClassVar[str] = 'json'
	TypeNames: ClassVar[tuple[str, ...]] = ('json5', 'structured-json')
	Suffixes: ClassVar[tuple[str, ...]] = ('.json', '.json5', '.jsonc')
	MimeTypes: ClassVar[tuple[str, ...]] = ('application/json', 'text/json')

	def _parse_data(self) -> Any:
		return json5.loads(self.to_text(normalize=False))

__all__ = ['JSON']
