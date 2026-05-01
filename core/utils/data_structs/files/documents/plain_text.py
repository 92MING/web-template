

from typing import ClassVar

from ._structured import PlainTextDoc


class PlainText(PlainTextDoc):
	'''无特定后缀的纯文本模型。'''

	Abstract: ClassVar[bool] = False
	Type: ClassVar[str] = 'plaintext'
	TypeNames: ClassVar[tuple[str, ...]] = ('text', 'plain')
	Suffixes: ClassVar[tuple[str, ...]] = ()
	MimePrefixes: ClassVar[tuple[str, ...]] = ()
	MimeTypes: ClassVar[tuple[str, ...]] = ('text/plain',)

__all__ = ['PlainText']
