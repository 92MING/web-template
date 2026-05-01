

from typing import ClassVar

from ._structured import DelimitedTableDocument


class TSV(DelimitedTableDocument):
	'''TSV 文档模型。'''

	Abstract: ClassVar[bool] = False
	Type: ClassVar[str] = 'tsv'
	TypeNames: ClassVar[tuple[str, ...]] = ('tab-separated-values',)
	Suffixes: ClassVar[tuple[str, ...]] = ('.tsv', '.tab')
	MimeTypes: ClassVar[tuple[str, ...]] = ('text/tab-separated-values',)
	Delimiter = '\t'

__all__ = ['TSV']
