import re

from typing import Final

COMMON_PUNCTUATIONS: Final[tuple[str, ...]] = (
    '.', ',', ';', ':', '?', '!', 
    '。', '，', '；', '：', '？', '！', '、', '…', '——', '—',
    '．', '､', '︰', '︙', '︱', '︳', '︴',
    '"', '"', '"', "'", "'", "'", '「', '」', '『', '』', 
    '〈', '〉', '《', '》', '【', '】', '〔', '〕',
    '(', ')', '（', '）', '[', ']', '［', '］', 
    '{', '}', '｛', '｝', '⟨', '⟩', '〖', '〗',
    '-', '–', '—', '―', '～', '~', '_', '＿',
    '|', '｜', '/', '／', '\\', '＼', '¦', '│',
    ' ', '\t', '\n', '\r', '\f', '\v', '\u00A0', '\u2000', '\u2001', 
    '\u2002', '\u2003', '\u2004', '\u2005', '\u2006', '\u2007', 
    '\u2008', '\u2009', '\u200A', '\u200B', '\u3000',
    '*', '＊', '×', '·', '•', '∙', '‧', '∗', '⋆', '★', '☆',
    '+', '＋', '=', '＝', '<', '>', '＜', '＞', '≤', '≥',
    '@', '＠', '#', '＃', '$', '＄', '%', '％', '^', '＾',
    '&', '＆', '§', '¶', '†', '‡', '°', '′', '″', '‴',
    '±', '∓', '÷', '∕', '∖', '∘', '∙', '√', '∝', '∞',
    '∠', '∥', '∦', '∧', '∨', '∩', '∪', '∫', '∮', '∴', '∵',
    '¢', '£', '¤', '¥', '€', '₹', '₽', '₩', '₪', '₫',
    '©', '®', '™', '℠', '℗', '№', '℃', '℉', '℧', '℩'
)
'''Common special punctuations used in text processing.'''

EMOJI_RE_PATTERN = re.compile(
    r'[\U0001F000-\U0001F0FF]|'  # Playing cards
    r'[\U0001F100-\U0001F1FF]|'  # Enclosed chars
    r'[\U0001F300-\U0001F5FF]|'  # Other additional symbols
    r'[\U0001F600-\U0001F64F]|'  # Emoticons
    r'[\U0001F680-\U0001F6C5]|'  # Transport and Map Symbols
    r'[\U0001F900-\U0001F9FF]|'  # Miscellaneous Symbols and Pictographs
    r'[\U0001FA70-\U0001FAFF]|'  
    r'[\U000023E9-\U000023F3]|'  # clock and button symbols
    r'[\U00002600-\U000026FF]|'  
    r'[\U00002700-\U000027BF]|'  # Dingbats
    r'[\U00002B00-\U00002BFF]|'  
    r'[\U00003200-\U000032FF]',  # Enclosed CJK Letters and Months
    flags=re.UNICODE
)
'''Regular expression pattern to match emojis in text.'''


__all__ = ['COMMON_PUNCTUATIONS', 'EMOJI_RE_PATTERN']


if __name__ == '__main__':
    print(EMOJI_RE_PATTERN.findall('🤧i是。'))