import random
import regex as re

from typing import Sequence
from lingua import LanguageDetectorBuilder, LanguageDetector, IsoCode639_1, IsoCode639_3, Language as _LinguaLang
from collections import OrderedDict

from .language import Language
from .chinese import (count_chinese, translate_chinese, ZHTranslationType, get_canton_to_pth_dict,
                      count_sentence, contains_chinese)
from .constants import COMMON_PUNCTUATIONS, EMOJI_RE_PATTERN

MAX_SHORT_CIRCUIT_LEN = 96
SPECIFIC_ZH_DETECTION_SAMPLE_COUNT = 128
DEFAULT_DETECTOR_CACHE_COUNT = 8
MAX_YUE_PHRASE_COUNT = 8

# since lingua is done by rust, enums are wrong
# the below codes fix those missing attrs in IsoCode639_1/3 enums
for _enum in (IsoCode639_1, IsoCode639_3):
    _members = {}
    for _attr in dir(_enum):
        if not _attr.startswith('_') and _attr.upper() == _attr:  # all uppercase
            enum_item = getattr(_enum, _attr)
            _members[_attr] = enum_item
    setattr(_enum, '__members__', _members)    # type: ignore

__AllLangDetectors__ = OrderedDict()

def _get_lang_enums(langs: Sequence[Language]|None)->list[_LinguaLang]|None:
    if not langs:
        return None
    langs = tuple([lang.code.lower() for lang in langs]) # type: ignore
    lang_enums = []
    for lang in langs:  # type: ignore
        lang_code_len = len(lang)   # type: ignore
        if lang in ('zh', 'yue') or lang.startswith('zh-'):  # type: ignore
            lang_enums.append(_LinguaLang.CHINESE)
        elif lang_code_len == 2:  # type: ignore
            for lang_enum_name, lang_code_enum in IsoCode639_1.__members__.items():
                if lang_enum_name.lower() == lang:
                    lang_enums.append(_LinguaLang.from_iso_code_639_1(lang_code_enum))
                    break
        elif lang_code_len == 3:
            for lang_enum_name, lang_code_enum in IsoCode639_3.__members__.items():
                if lang_enum_name.lower() == lang:
                    lang_enums.append(_LinguaLang.from_iso_code_639_3(lang_code_enum))
                    break
        else:
            raise ValueError(f'Invalid language code: {lang}')
    return lang_enums

def _get_or_create_lang_detectors(langs: list[_LinguaLang]|None = None)->LanguageDetector: # type: ignore
    if langs:
        lang_strs = [lang.name for lang in langs]
        lang_strs.sort()    # sort to make sure the order is consistent
        dict_identifier = tuple(lang_strs)
    else:
        dict_identifier = None
    if dict_identifier in __AllLangDetectors__:
        detector = __AllLangDetectors__[dict_identifier]
    else:
        if len(__AllLangDetectors__) >= DEFAULT_DETECTOR_CACHE_COUNT:
            __AllLangDetectors__.popitem(last=False)    # FIFO
        if langs:
            detector = LanguageDetectorBuilder.from_languages(*langs).with_low_accuracy_mode().build()
        else:
            detector = LanguageDetectorBuilder.from_all_languages().with_low_accuracy_mode().build()
        __AllLangDetectors__[dict_identifier] = detector
    return detector

def _tidy_languages(languages: str|Language|Sequence[str|Language]|None)->list[Language]:
    if isinstance(languages, (str, Language)):
        languages = [languages]
    
    tidied_langs: list[Language] = []
    if languages:
        for l in languages:
            if isinstance(l, str):
                if l == 'zh':
                    tidied_langs.append(Language.SimplifiedChinese)
                    tidied_langs.append(Language.TraditionalChinese)
                else:
                    l = Language.Find(l)
                    if not l:
                        raise ValueError(f'Invalid language code: {l}')
                    else:
                        tidied_langs.append(l)
            else:
                tidied_langs.append(l)
    return tidied_langs

def detect_language(
    text: str, 
    languages: str|Language|Sequence[str|Language]|None=None,
)->Language|None:
    '''
    Detect language. Returns none if no language detected.
    
    Args:
        - text: The text to detect language. Note: for short text, the detection accuracy may be low.
        - languages: The languages restricted to detect. If `None`, detect all languages.
        - ignore_err: If `True`, if unknown language code is given, they will be ignored. 
                      Otherwise, raise error.
    '''
    text = text.strip()
    if text.isdigit():
        return None
    
    if isinstance(languages, (str, Language)):
        languages = [languages]
    
    tidied_langs: list[Language] = []
    if languages:
        tidied_langs = _tidy_languages(languages)
        check_tw = Language.TraditionalChinese in tidied_langs
        check_cn = Language.SimplifiedChinese in tidied_langs
        check_yue = Language.Cantonese in tidied_langs
    else:
        check_tw = check_cn = check_yue = True
    
    lang_enums = _get_lang_enums(tidied_langs)
    detect_single_lang = (len(lang_enums) == 1) if lang_enums else False
    first_lang_enum = lang_enums[0] if lang_enums else None
    
    detected_lang_enum: _LinguaLang|None = None
    if len(text) < MAX_SHORT_CIRCUIT_LEN:
        if lang_enums is None or _LinguaLang.ENGLISH in lang_enums:
            if text.isascii():
                detected_lang_enum = _LinguaLang.ENGLISH
    
    if not detected_lang_enum:
        if detect_single_lang:
            detector = _get_or_create_lang_detectors()  # detect all lang, and finally check result == first_lang_enum
        else:
            detector = _get_or_create_lang_detectors(lang_enums)
        detected_lang_enum = detector.detect_language_of(text)
    
    if not detected_lang_enum and count_chinese(text)/len(text) >= 0.4:
        detected_lang_enum = _LinguaLang.CHINESE
    
    if detected_lang_enum == _LinguaLang.CHINESE:
        if not contains_chinese(text):
            return None
        
        # detect zh-cn/zh-tw/zh-yue
        if check_yue and not (check_tw or check_cn):
            return Language.Cantonese
        if check_tw and not (check_cn or check_yue):
            return Language.TraditionalChinese
        if check_cn and not (check_tw or check_yue):
            return Language.SimplifiedChinese
        
        if check_yue:
            canton_keys = list(get_canton_to_pth_dict().keys())
            cantonese_words = {'嘅', '咗', '嗰', '喺', '啲', '咩', '撚', '冇', '佢', '唔', '哋', '咁'}
            cantonese_words.update(canton_keys)
            longest_key_len = max(len(key) for key in cantonese_words)
            
            sentence_count = count_sentence(text)
            phrases_needed = min(sentence_count, MAX_YUE_PHRASE_COUNT)
            def check_canton(i:int, text: str):
                if i>=len(text):
                    return False, None
                for j in range(longest_key_len, 0, -1):
                    if i+j <= len(text):
                        continue
                    if text[i:i+j] in cantonese_words:
                        return True, i+j
                return False, None
                    
            cantonese_words_count = 0
            for i in range(len(text)):
                found, next_i = check_canton(i, text)
                if found:
                    cantonese_words_count += 1
                    if cantonese_words_count >= phrases_needed:
                        return Language.Cantonese
                if next_i:
                    i = next_i
                else:
                    i += 1
                if i >= len(text):
                    break
        
        if check_tw or check_cn:
            if check_tw and not check_cn:
                return Language.TraditionalChinese
            if check_cn and not check_tw:
                return Language.SimplifiedChinese
            
            chars_to_remove = [' ', '\n', '\t', '_', '-', '(', ')', '[', ']', '{', '}', '<', '>', '!', '?', '!', '？', '！', '(', ')', '（', '）', '「', '」', '【', '】', '《', '》', '“', '”', '‘', '’', '‧', '•', '·', '…', '—',
                                '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '０', '１', '２', '３', '４', '５', '６', '７', '８', '９', '％', '%', '＋', '+', '－', '-', '＝', '=', '＜', '<', '＞', '>', '＆', '&', '＊', '*', '＃', '#',
                                '＠', '@', '＼', '\\', '／', '/', '｜', '|', '：', ':', '；', ';', '，', ',', '、', '。', '．', '.', '？', '?', '！', '!', '～', '~', '＂', '"', '＇', "'", '＂', '"', '＃', '#', '＄', '$', '％', '%', '＆']
            chars_to_remove.extend([chr(i) for i in range(0, 256) if not chr(i).isprintable()])
            chars_to_remove = set(chars_to_remove)
            tidied_text = ''.join([char for char in text if char not in chars_to_remove])
            # Only sample CJK characters for zh-cn vs zh-tw detection;
            # ASCII letters/numbers are not meaningful for this distinction.
            cjk_chars = [c for c in tidied_text if '\u4e00' <= c <= '\u9fff']
            if not cjk_chars:
                return Language.SimplifiedChinese
            testing_pool = random.sample(cjk_chars, min(SPECIFIC_ZH_DETECTION_SAMPLE_COUNT, len(cjk_chars)))
            zhtw_count = 0
            zhcn_count = 0
            for char in testing_pool:
                tw_to_cn_succ = (translate_chinese(char, ZHTranslationType.Trad2Sim) != char)
                cn_to_tw_succ = (translate_chinese(char, ZHTranslationType.Sim2Trad) != char)
                if tw_to_cn_succ and not cn_to_tw_succ: # only tw to cn, means tw
                    zhtw_count += 1
                elif cn_to_tw_succ and not tw_to_cn_succ: # only cn to tw, means cn
                    zhcn_count += 1
            ratio = zhtw_count / (zhtw_count + zhcn_count) if (zhtw_count + zhcn_count) > 0 else 0
            if ratio <= 0.5 and zhcn_count > min(512, max(len(tidied_text)*0.1, 1)):
                return Language.SimplifiedChinese
            elif zhtw_count > min(512, max(len(tidied_text)*0.1, 1)):
                return Language.TraditionalChinese
            else:
                return None  # cannot decide
    
    if detected_lang_enum:
        if detect_single_lang and detected_lang_enum != first_lang_enum:
            return None  # if only one language is specified, and the detected language is not the same, return None
        lang = Language.Find(detected_lang_enum.iso_code_639_1.name)
        if not lang:
            raise ValueError(f'Invalid language code: {detected_lang_enum.name}')
    else:
        lang = None
    return lang

def include_language_character(text: str) -> bool:
    '''
    Check if the text contains any language character,
    i.e. any character that is not a digit or punctuation.
    '''
    pattern = re.compile(r'[\p{L}]', re.UNICODE)
    return bool(pattern.search(text))

def count_words(
    text: str, 
    count_number: bool=True,
    count_emoji: bool=True,
    lang: Language|str|None=None
)->int:
    '''
    Count words in the text.
    Different language will have different word counting rules,
    e.g. Chinese will count each character as a word, English will count each 
    word separated by space as a word.
    
    Args:
        - text: The text to count words.
        - count_number: If `True`, count numbers as 1 words.
        - count_emoji: If `True`, count emojis as 1 words.
        - lang: The language of the text. If not specified, will try to detect the language.
    '''
    if not lang:
        lang = detect_language(text)
    elif isinstance(lang, str):
        lang = Language.Find(lang)
        if not lang:
            raise ValueError(f'Invalid language code: {lang}')
    char_counting_langs = (Language.SimplifiedChinese, Language.TraditionalChinese, Language.Cantonese,
                           Language.Japanese, Language.Korean, Language.Vietnamese, Language.Thai)
    count = 0
    if count_number:
        number_pattern = re.compile(r'\d+(?:\.\d+)?', re.UNICODE)
        count += len(number_pattern.findall(text))
        text = number_pattern.sub(' ', text)  # remove numbers from text for further counting
    if count_emoji:
        count += len(EMOJI_RE_PATTERN.findall(text))
        text = EMOJI_RE_PATTERN.sub(' ', text)

    is_char_counting = (lang in char_counting_langs) if lang else False
    special_chars_pattern = r'|'.join(re.escape(char) for char in COMMON_PUNCTUATIONS)
    special_chars_pattern += r'|[\s]+'  # also split by whitespace
    special_chars_pattern = re.compile(special_chars_pattern, re.UNICODE)
    
    if is_char_counting:
        text = special_chars_pattern.sub('', text)  # remove special chars
        count += len(text)
    else:
        chunks = list(filter(
            lambda x: bool(x.strip()),
            special_chars_pattern.split(text),
        ))   # split by special chars
        count += len(chunks)
    return count


def word_count(
    text: str,
    count_number: bool = True,
    count_emoji: bool = True,
) -> int:
    '''Count words in potentially mixed-language text.

    Unlike ``count_words()``, this function handles text that mixes multiple
    writing systems by segmenting it into CJK / character-level blocks and
    non-CJK blocks independently:

    * **CJK segment** (Han, Hiragana/Katakana, Hangul, Thai, …): each
      character counts as one "word".
    * **Non-CJK segment**: split on punctuation / whitespace and count tokens.

    This avoids the common pitfall of ``detect_language()`` picking whichever
    language occupies the majority and applying uniform counting to the whole
    text.

    Args:
        text: The text to count.
        count_number: If ``True``, each contiguous number group counts as 1 word.
        count_emoji: If ``True``, each emoji counts as 1 word.

    Returns:
        Estimated word / token count.
    '''
    if not text:
        return 0

    count = 0

    if count_number:
        number_pattern = re.compile(r'\d+(?:\.\d+)?', re.UNICODE)
        count += len(number_pattern.findall(text))
        text = number_pattern.sub(' ', text)

    if count_emoji:
        count += len(EMOJI_RE_PATTERN.findall(text))
        text = EMOJI_RE_PATTERN.sub(' ', text)

    # Build token-split pattern (same as count_words uses)
    _split_pat = re.compile(
        r'|'.join(re.escape(c) for c in COMMON_PUNCTUATIONS) + r'|[\s]+',
        re.UNICODE,
    )

    # CJK and other character-level scripts
    # Ranges: Hangul Jamo, CJK Radicals, CJK Symbols/Punct, Hiragana, Katakana,
    #         Bopomofo, Hangul Compat. Jamo, CJK Ext-A, CJK Unified Ideographs,
    #         Hangul Jamo Ext-A, Hangul Syllables + Jamo Ext-B,
    #         CJK Compat. Ideographs, CJK Compat. Forms, Thai
    _CJK_PAT = re.compile(
        r'[\u1100-\u11FF'   # Hangul Jamo
        r'\u2E80-\u2EFF'    # CJK Radicals Supplement
        r'\u3000-\u303F'    # CJK Symbols and Punctuation
        r'\u3040-\u30FF'    # Hiragana + Katakana
        r'\u3100-\u318F'    # Bopomofo + Hangul Compat. Jamo
        r'\u3400-\u4DBF'    # CJK Unified Ideographs Extension A
        r'\u4E00-\u9FFF'    # CJK Unified Ideographs
        r'\uA960-\uA97F'    # Hangul Jamo Extended-A
        r'\uAC00-\uD7FF'    # Hangul Syllables + Jamo Extended-B
        r'\uF900-\uFAFF'    # CJK Compatibility Ideographs
        r'\uFE30-\uFE4F'    # CJK Compatibility Forms
        r'\u0E00-\u0E7F'    # Thai
        r']+',
        re.UNICODE,
    )

    last_end = 0
    for m in _CJK_PAT.finditer(text):
        start, end = m.start(), m.end()
        # Non-CJK segment before this CJK block → token count
        non_cjk = text[last_end:start]
        if non_cjk.strip():
            tokens = [t for t in _split_pat.split(non_cjk) if t.strip()]
            count += len(tokens)
        # CJK block → character count (ignore whitespace inside)
        cjk_clean = re.sub(r'\s+', '', m.group())
        count += len(cjk_clean)
        last_end = end

    # Trailing non-CJK segment
    remaining = text[last_end:]
    if remaining.strip():
        tokens = [t for t in _split_pat.split(remaining) if t.strip()]
        count += len(tokens)

    return count


__all__ = ['detect_language', 'include_language_character', 'count_words', 'word_count']


if __name__ == '__main__':    
    def test_detect_lang():
        print(detect_language('Hello?'))    # en
        print(detect_language('你好'))  # zh-cn
        print(detect_language('繁體'))  # zh-tw
        print(detect_language('你係邊個'))  # zh-yue
        print(detect_language('مجھے ہانگ کانگ میں طلاق کیسے حاصل کرنی چاہئ')) # ur
        # zh-cn
        print(detect_language('''另外一些：
    有时候我们也会用到全角英文、特殊符号等
    全角英文的UTF8是: uff21 – uff5a ，是从大写A开始到小写的z。
    utf8中的 uff20是@
    utf8中的 uff01到 uff09是我们美式键盘上shift + 从1到9键上的特殊符号。要注意的是因为@是 uff20，所以 uff02是双引号，同时6的……是两个符号的组合，所以也不存在，正题提前一位（也就是说ff06是＆， ff09是））。
    utf8中的全角数字是 uff10 – uff19 ，对应关系自然是０ – ９ 。''')) 

        # zh-tw
        print(detect_language('UTF-8（8-bit Unicode Transformation Format）是一種針對Unicode的可變長度字元編碼，也是一種字首碼。它可以用一至四個位元組對Unicode字元集中的所有有效編碼點進行編碼，屬於Unicode標準的一部分，最初由肯·湯普遜和羅布·派克提出。[2][3]由於較小值的編碼點一般使用頻率較高，直接使用Unicode編碼效率低下，大量浪費主記憶體空間。UTF-8就是為了解決向下相容ASCII碼而設計，Unicode中前128個字元，使用與ASCII碼相同的二進位值的單個位元組進行編碼，而且字面與ASCII碼的字面一一對應，這使得原來處理ASCII字元的軟體無須或只須做少部份修改，即可繼續使用。因此，它逐漸成為電子郵件、網頁及其他儲存或傳送文字優先採用的編碼方式。'))
        # en
        print(detect_language('US President Joe Biden has admitted he \\"screwed up\\" in last week\'s debate against Donald Trump, but has vowed to fight on in the election race and moved to reassure key allies.\\nHe told a Wisconsin radio station he made a \\"mistake\\" with his stumbling performance, but urged voters to instead judge him on his time in the White House.\\nOn Wednesday, as reports suggested he was weighing his future, he worked to calm senior Democrats including state governors and campaign staff.\\n\\u201cI\'m the nominee of the Democratic Party. No one\'s pushing me out. I\'m not leaving,\\" he said in a call to the broader campaign, a source told BBC News.\\nMr Biden was joined on the call by Vice-President Kamala Harris, who reiterated her support.'))
    
    def test_detect_lang_limited():
        print(detect_language('你好', [Language.SimplifiedChinese, Language.English]))  # zh-cn
    
    def test_count_words():
        print(count_words('Hello, world!')) # 2
        print(count_words('你好，世界！')) # 4
    def test_length():
        a = [' 8.', 'Wages', ' (a) wage rate ', 'Basic wages of $ ___________________ per *hour / day / week / month;', 'plus the following allowance(s) :  ', ' Meal allowance of $ ___________________ per *day / week / month', ' Travelling allowance of $ _______________ per *day / week / month', ' Attendance allowance of $ __________________________________________________', '             (please specify details of payment criteria, calculation method, etc.)', ' Others (e.g. commission, tips) $ ______________________________________________ ', '(please specify details of payment criteria, calculation method, date of payment, etc.)', ' ', '(b) payment of', ' wages & wage', ' Every month, on ____________ day of the month for wage period from ______ day of the month to ______ day of *the month / the following month', 'priod(s) †', ' Twice monthly, payable on', '- _________ day of *the month / the following month  ', 'for wage period from ______ day of the month to ______ day of *the month / the following month; and', '- _________ day of *the month / the following month']
        count=0
        for p in a:
            if not detect_language(p) == Language.TraditionalChinese and include_language_character(p):
                count += 1
        print(count)
        
    # test_detect_lang_limited()
    # test_length()
    x = detect_language('abcdefg', languages=[Language.SimplifiedChinese, Language.TraditionalChinese])
    print(x)