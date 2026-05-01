

from typing import ClassVar

from ._structured import XMLLikedDocument


class XML(XMLLikedDocument):
	'''XML 文档模型。'''

	Abstract: ClassVar[bool] = False
	Type: ClassVar[str] = 'xml'
	TypeNames: ClassVar[tuple[str, ...]] = ('rss', 'atom', 'xhtml', 'svg')
	Suffixes: ClassVar[tuple[str, ...]] = ('.xml', '.xsd', '.rss', '.atom', '.svg')
	MimeTypes: ClassVar[tuple[str, ...]] = ('application/xml', 'text/xml')

__all__ = ['XML']
