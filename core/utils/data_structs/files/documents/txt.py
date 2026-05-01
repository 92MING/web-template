

from typing import ClassVar

from ._structured import PlainTextDoc


class TXT(PlainTextDoc):
	'''TXT 文档模型。'''

	Abstract: ClassVar[bool] = False
	Type: ClassVar[str] = 'txt'
	TypeNames: ClassVar[tuple[str, ...]] = ('textfile',)
	Suffixes: ClassVar[tuple[str, ...]] = ('.txt', '.text')
	MimeTypes: ClassVar[tuple[str, ...]] = ('text/plain',)

__all__ = ['TXT']
