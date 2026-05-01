

from typing import ClassVar

from ._structured import DelimitedTableDocument


class CSV(DelimitedTableDocument):
	'''CSV 文档模型。'''

	Abstract: ClassVar[bool] = False
	Type: ClassVar[str] = 'csv'
	TypeNames: ClassVar[tuple[str, ...]] = ()
	Suffixes: ClassVar[tuple[str, ...]] = ('.csv',)
	MimeTypes: ClassVar[tuple[str, ...]] = ('text/csv',)
	Delimiter = ','

__all__ = ['CSV']
