import os
import re
import json
import random
import opencc
import logging

from enum import Enum
from hashlib import md5
from pathlib import Path
from random import choice
from opencc import OpenCC
from typing import Literal, TYPE_CHECKING
from functools import cache
from dataclasses import dataclass
from platformdirs import user_cache_dir
from collections import OrderedDict

from ..build_utils import build_cython as _build_cython

_chinese_fast = _build_cython(Path(os.path.join(os.path.dirname(__file__), '_chinese_fast.pyx')))
_CantonTrie = _chinese_fast.CantonTrie

_logger = logging.getLogger(__name__)
_zh_pattern = re.compile(r'[\u2E80-\u9FFF]')
_zh_strict_pattern = re.compile(r'[\u4E00-\u9FA5]')

def count_chinese(text: str, strict_mode: bool=True):
    '''
    Count the number of Chinese characters by looking to the UTF-8 range.
    For `strict_mode`=True, the checking range will be more smaller, otherwise some
    non-Chinese characters (japanese, korean, ...) will be considered as Chinese.
    '''
    if not strict_mode:
        r = re.findall(_zh_pattern, text)
    else:
        r = re.findall(_zh_strict_pattern, text)
    return len(r)

def contains_chinese(text: str, strict_mode: bool = True):
    '''
    Check if text contains Chinese characters by looking to the UTF-8 range.
    For `strict_mode`=True, the checking range will be more smaller, otherwise some
    non-Chinese characters (japanese, korean, ...) will be considered as Chinese.
    '''
    return count_chinese(text, strict_mode) > 0

type _ZHType = Literal['s', 't']

def detect_chinese_type(text: str, fallback: _ZHType='s')->_ZHType|None:
    '''
    Detect the type of Chinese text.
    
    Args:
        - text: The text to be detected.
        - fallback: The fallback type if simplified or traditional chars has equal count.
    
    Returns:
        - 's' for simplified Chinese
        - 't' for traditional Chinese
        - `None` for non-Chinese text
    '''
    text = text.strip()
    if not text:
        return None
    zh_chars = re.findall(_zh_pattern, text)
    if (len(zh_chars)/len(text)) < 0.15:
        return None
    
    count = s_counts = t_counts = 0
    threshold = min(len(zh_chars), 128)
    while zh_chars:
        c = choice(zh_chars)
        zh_chars.remove(c)
        ct = translate_chinese(c, ZHTranslationType.Sim2Trad)
        cs = translate_chinese(c, ZHTranslationType.Trad2Sim)
        if ct != cs:
            count += 1
            if ct == c:
                t_counts += 1
            else:
                s_counts += 1
            if count >= threshold and (s_counts != t_counts):
                break
            
    if s_counts == t_counts:
        return fallback
    if s_counts > t_counts:
        return 's'
    return 't'

def random_chinese_text(length: int = 1024, strict_mode: bool=True):
    '''
    Generate random Chinese text.
    For `strict_mode`=True, the generated text will be more likely to be Chinese,
    i.e. some japanese, korean characters will be excluded.
    '''
    text = ''
    for _ in range(length):
        # CJK Unified Ideographs
        if strict_mode:
            code_point = random.randint(0x4E00, 0x9FA5)
        else:
            code_point = random.randint(0x2E80, 0x9FFF)    
        text += chr(code_point)
    return text

type _ZHTranslationTypeLiteral = Literal[
    't2s', 's2t', 'hk2s', 's2hk', 'tw2s', 's2tw', 'tw2sp', 's2twp', 't2hk', 't2tw'
]

class ZHTranslationType(Enum):
    '''Translation type for Chinese'''
    Trad2Sim = 't2s'
    '''traditional chinese to simplified chinese'''
    Sim2Trad = 's2t'
    '''simplified chinese to traditional chinese'''
    HK2Sim = 'hk2s'
    '''hongkong chinese to simplified chinese'''
    Sim2HK = 's2hk'
    '''simplified chinese to hongkong chinese'''
    TW2Sim = 'tw2s'
    '''taiwan chinese to simplified chinese'''
    Sim2TW = 's2tw'
    '''simplified chinese to taiwan chinese'''
    TW2SimWithPhrases = 'tw2sp'
    '''taiwan chinese to simplified chinese, with phrases'''
    Sim2TWWithPhrases = 's2twp'
    '''simplified chinese to taiwan chinese, with phrases'''
    Trad2HK = 't2hk'
    '''traditional chinese to hongkong chinese'''
    Trad2TW = 't2tw'
    '''traditional chinese to taiwan chinese'''

    @classmethod
    def FromStr(cls, s: str):
        s = s.lower().strip()
        for item in cls:
            if item.value == s:
                return item
        raise ValueError(f'Unknown ZHTranslationType: {s}')

__zh_translators__ = {}
_curr_dir = os.path.dirname(os.path.abspath(__file__))
_opencc_resources_dir = os.path.join(os.path.dirname(opencc.__file__), 'clib', 'share', 'opencc')
_cache_dir = user_cache_dir('proj-opencc-extra')

@cache
def _get_opencc_s2t_config_path():
    if not os.path.exists(_cache_dir):
        os.makedirs(_cache_dir, exist_ok=True)
    st_extra_dict_path = _get_opencc_s2t_extra_dict_path()
    curr_hash = os.path.basename(st_extra_dict_path).split('.')[0]
    # Save without .json extension - OpenCC will add it
    config_path_without_ext = os.path.join(_cache_dir, curr_hash)
    config_path_with_ext = config_path_without_ext + '.json'

    if not os.path.exists(config_path_with_ext):
        st_phrases_ocd2_path = os.path.join(_opencc_resources_dir, 'STPhrases.ocd2')
        st_chars_ocd2_path = os.path.join(_opencc_resources_dir, 'STCharacters.ocd2')
        config = {
            "name": "Simplified Chinese to Traditional Chinese",
            "segmentation": {
                "type": "mmseg",
                "dict": {
                    "type": "group",
                    "dicts": [
                        {
                            "type": "text",
                            "file": st_extra_dict_path
                        },
                        {
                            "type": "ocd2",
                            "file": st_chars_ocd2_path
                        }
                    ]
                }
            },
            "conversion_chain": [
                {
                    "dict": {
                        "type": "group",
                        "dicts": [
                            {
                                "type": "ocd2",
                                "file": st_phrases_ocd2_path
                            },
                            {
                                "type": "ocd2",
                                "file": st_chars_ocd2_path
                            }
                        ]
                    }
                }
            ]
        }
        with open(config_path_with_ext, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    # Return path without .json - OpenCC will add it
    return config_path_without_ext

@cache
def _get_opencc_s2t_extra_dict_path():
    if not os.path.exists(_cache_dir):
        os.makedirs(_cache_dir, exist_ok=True)
    with open(os.path.join(_curr_dir, 'opencc_s2t_extra.txt'), 'r', encoding='utf-8') as f:
        data = f.read()
        curr_hash = md5(data.encode('utf-8')).hexdigest()
        extra_dict_path = os.path.join(_cache_dir, f'{curr_hash}.txt')
        if not os.path.exists(extra_dict_path):
            lines = data.splitlines()
            tidied = []
            for line in lines:
                line = line.strip()
                if not line or line.startswith('//'):
                    continue
                parts = line.strip().split()
                if len(parts) >= 2:
                    f_part = parts[0].strip()
                    b_part = parts[1].strip()
                    if f_part and b_part:
                        tidied.append(f"{f_part}\t{b_part}")
            with open(extra_dict_path, 'w', encoding='utf-8') as out_f:
                out_f.write('\n'.join(tidied))
    return extra_dict_path

def _get_zh_translator(type: ZHTranslationType) -> OpenCC:
    if type.value not in __zh_translators__:
        if type.value == 's2t':
            config = _get_opencc_s2t_config_path()
        else:
            config = type.value

        # Try to initialize OpenCC, handling different versions
        # Some versions expect path without .json, others expect with .json
        try:
            translator = OpenCC(config)
        except FileNotFoundError as e:
            # If it failed because of .json.json issue, try with .json added
            if '.json.json' in str(e) and type.value == 's2t':
                config_with_json = config + '.json'
                translator = OpenCC(config_with_json)
            else:
                raise

        __zh_translators__[type.value] = translator
    return __zh_translators__[type.value]

def translate_chinese(
    text: str, 
    type: ZHTranslationType|_ZHTranslationTypeLiteral, 
) -> str:
    '''
    Change chinese text from one type to another, e.g. from simplified to traditional.
    Args:
        - text: The text to be translated.
        - type: The type of translation, e.g. ZHTranslationType.Simplified 
    '''
    if isinstance(type, str):
        type = ZHTranslationType.FromStr(type)
    if text.isascii():
        return text
    return _get_zh_translator(type).convert(text)   # type: ignore

def count_sentence(text: str, split_comma: bool=True)->int:
    '''
    Count the number of sentences in the text.
    If `split_comma` is True, sentences like `a,b,c` will be counted as 3 sentences.
    '''
    MIN_SENTENCE_LEN = 3
    split_chars = ['。', '！', '？', '!', '\\?', '\\s', '\\n', '\\t', '；', ';', '：', ':']
    if split_comma:
        split_chars.extend([',', '，'])
    split_pattern = re.compile('|'.join(split_chars))
    sentences = split_pattern.split(text)
    return len([s for s in sentences if len(s) >= MIN_SENTENCE_LEN])


__all__ = [
    'count_chinese',
    'contains_chinese', 
    'detect_chinese_type',
    'random_chinese_text', 
    'ZHTranslationType', 
    'translate_chinese', 
    'count_sentence',
]

# region cantonese to mandarin
_cantonese_to_mandarin_dict = None

def get_canton_to_pth_dict()->OrderedDict[str, str]:
    '''A dict(sorted by key len) which maps cantonese phrases to mandarin, e.g. {'唔該': '感謝'...}'''
    global _cantonese_to_mandarin_dict
    if _cantonese_to_mandarin_dict is None: 
        _canton_pth_dict_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'canton_dict.json')
        if (os.path.exists(_canton_pth_dict_path)):
            _logger.debug(f'Loading cantonese to mandarin dict from {_canton_pth_dict_path}...')
            with open(_canton_pth_dict_path, 'r', encoding='utf-8') as f:
                _cantonese_to_mandarin_dict = json.loads(f.read())
                
            for key in tuple(_cantonese_to_mandarin_dict.keys()):   # type: ignore
                if len(key) == 1:
                    # remove single character, since they are dangerous to replace
                    del _cantonese_to_mandarin_dict[key]    # type: ignore    
            _cantonese_to_mandarin_dict = OrderedDict(sorted(_cantonese_to_mandarin_dict.items(),   # type: ignore 
                                                             key=lambda t: len(t[0]), 
                                                             reverse=True)) 
        else:
            _logger.debug(f'Fail to find cantonese to mandarin dict file.')
            _cantonese_to_mandarin_dict = OrderedDict()
    return _cantonese_to_mandarin_dict

@dataclass
class _ReplaceComp:
    
    origin_text: str
    new_text: str = None    # type: ignore
    
    head: '_ReplaceComp' = None # type: ignore
    tail: '_ReplaceComp' = None # type: ignore

    @property
    def replaced(self):
        return (self.new_text is not None) or len(self.origin_text) <= 1    # no need to replace single character
    
    def __iter__(self):
        comp = self
        while comp is not None:
            yield comp
            comp = comp.tail
    @property
    def text(self):
        return self.new_text or self.origin_text
    @property
    def top_head(self):
        head = self
        while head.head:
            head = head.head
        return head
    def get_full_text(self):
        text = ''
        for comp in self.top_head:
            text += comp.text
        return text
    @property
    def all_done(self):
        for comp in self.top_head:
            if not comp.replaced:
                return False
        return True
    
_cantonese_trie_cache = None  # type: _CantonTrieType | None  # noqa: E501

def _get_canton_trie():
    """Build (or return cached) Cython CantonTrie from the canton dict."""
    global _cantonese_trie_cache
    if _cantonese_trie_cache is not None:
        return _cantonese_trie_cache
    if _CantonTrie is None:
        return None
    d = get_canton_to_pth_dict()
    trie = _CantonTrie()
    trie.build(dict(d))
    _cantonese_trie_cache = trie
    return trie

def _internal_simple_canton_2_PTH(text: str):
    '''translate cantonese to mandarin by replacing words'''
    # Fast-path: Cython trie-based single-pass replacer
    trie = _get_canton_trie()
    if trie is not None:
        return trie.replace(text)

    # Fallback: original linked-list approach
    real_head = _ReplaceComp(origin_text='', new_text='')
    head = _ReplaceComp(origin_text=text, head=real_head)
    real_head.tail = head
    done = False
    _cantonese_to_mandarin_dict = get_canton_to_pth_dict()
    for key, value in _cantonese_to_mandarin_dict.items():
        if done:
            break
        comp = real_head.tail
        while comp:
            if not comp.replaced:
                origin = comp.origin_text
                if (index := origin.find(key))!=-1:   # if replaced
                    before = origin[:index]
                    after = origin[index + len(key):]
                    new_comp = _ReplaceComp(origin_text=origin[index:index + len(key)], new_text=value)
                    if before:
                        before_comp = _ReplaceComp(origin_text=before, head=comp.head, tail=new_comp)
                        new_comp.head = before_comp
                        if comp.head:
                            comp.head.tail = before_comp
                    else:
                        new_comp.head = comp.head
                        if comp.head:
                            comp.head.tail = new_comp
    
                    if after:
                        after_comp = _ReplaceComp(origin_text=after, head=new_comp, tail=comp.tail)
                        new_comp.tail = after_comp
                        if comp.tail:
                            comp.tail.head = after_comp
                    else:
                        new_comp.tail = comp.tail
                        if comp.tail:
                            comp.tail.head = new_comp
                        
                    if before:
                        comp = before_comp  # go back to before_comp
                    else:
                        comp = new_comp.tail
                else:
                    comp = comp.tail
            else:
                comp = comp.tail
        if real_head.all_done:
            done = True
    return real_head.get_full_text()

def simple_canton_2_PTH(text: str) -> str:
    '''
    粵語轉書面語。（not AI, just converting by a simple dict）
    Text will also translated to traditional Chinese after conversion.
    '''
    text = translate_chinese(text, ZHTranslationType.Sim2Trad)
    return _internal_simple_canton_2_PTH(text)

__all__ += [
    'get_canton_to_pth_dict',
    'simple_canton_2_PTH',
]
# endregion


if __name__ == "__main__":
    print(detect_chinese_type('请问你是谁'))
    print(detect_chinese_type('請問你是誰'))
    print(translate_chinese("请问你是谁", ZHTranslationType.Sim2Trad))
    print(translate_chinese("液面", ZHTranslationType.Sim2Trad))
