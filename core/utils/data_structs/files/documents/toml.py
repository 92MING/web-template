

from typing import Any, ClassVar

from ._structured import DictLikedDocument

try:
	import tomllib
except Exception:  # pragma: no cover
	tomllib = None  # type: ignore[assignment]


class TOML(DictLikedDocument):
	'''TOML 文档模型。'''

	Abstract: ClassVar[bool] = False
	Type: ClassVar[str] = 'toml'
	TypeNames: ClassVar[tuple[str, ...]] = ()
	Suffixes: ClassVar[tuple[str, ...]] = ('.toml',)
	MimeTypes: ClassVar[tuple[str, ...]] = ('application/toml',)

	def _parse_data(self) -> Any:
		if tomllib is None:
			raise RuntimeError('tomllib is not available in this Python runtime.')
		return tomllib.loads(self.to_text(normalize=False))

__all__ = ['TOML']
