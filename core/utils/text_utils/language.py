import os
import json
import logging

from enum import Enum
from dataclasses import dataclass
from pydantic_core import core_schema
from typing import Self, TYPE_CHECKING, override

from ..data_structs import FuzzyDict

_language_thanks_dict = None
_language_prompt_dict = None

_logger = logging.getLogger(__name__)

def _get_resources(name: str)->dict|None:
    try:
        with open(os.path.join(os.path.dirname(__file__), name), 'r', encoding='utf-8') as f:
            return json.loads(f.read())
    except (json.JSONDecodeError, FileNotFoundError):
        return None

def _get_language_thx_dict()->dict[str, str]:
    global _language_thanks_dict
    if _language_thanks_dict is None:
        data = _get_resources('language_thanks.json')
        if data is None:
            _logger.warning('`language_thanks.json` not found or invalid in common resources path. Fail to load language-thanks dict.')
            _language_thanks_dict = {}
        else:
            _language_thanks_dict = data
    return _language_thanks_dict    # type: ignore

def _get_language_prompt_dict()->dict[str, str]:
    '''{lang_code: `Answer in {language}` in that language}'''
    global _language_prompt_dict
    if _language_prompt_dict is None:
        data = _get_resources('language_prompt.json')
        if data is None:
            _logger.warning('`language_prompt.json` not found or invalid in common resources path. Fail to load language prompt dict.')
            _language_prompt_dict = {}
        else:
            _language_prompt_dict = data
    return _language_prompt_dict    # type: ignore
        
@dataclass
class LanguageInfo:
    '''Information of a language.'''
    code: str
    '''
    Code of this language. For non-chinese, it follows ISO 639-1 code, e.g. 'en'.
    For Chinese, it follows 'zh-cn'/'zh-tw'/'zh-yue'.
    '''
    iso_639_1: str
    '''ISO 639-1 code of this language.'''
    iso_639_3: str
    '''ISO 639-3 code of this language.'''
    origin_name: str
    '''origin name of this language, e.g. 'English' for 'en'.'''
    microsoft_lang: str|None = None
    '''Microsoft language code of this language, e.g. 'zh-Hans' for Simplified Chinese.'''
    aliases: tuple[str, ...] = tuple()
    '''aliases of this language.'''
    duckduckgo_lang: str = 'wt-wt'
    '''region code when passing as query to DuckDuckGo'''
    
    def __eq__(self, other)->bool:
        if isinstance(other, str):
            other = other.lower().replace('_', '-')
            if other == 'zh':
                return self.code.split('-')[0] == 'zh'
            return other in (self.code, self.iso_639_1, self.iso_639_3, *self.aliases)
        return super().__eq__(other)
    
    @property
    def thanks_for_your_question_text(self)->str|None:
        '''
        `Thanks for your question` in this language, e.g. "谢谢你的提问" when `zh-cn`.
        Note that only some languages have this value.
        This is helpful for chatbot to response to user's question.
        '''
        return _get_language_thx_dict().get(self.code, None)
    
    @property
    def language_prompt(self)->str|None:
        '''
        `Answer in <language>` in this language, e.g. "用中文回答" when `zh-cn`.
        Note that only some languages have this value.
        This is helpful for chatbot to response to user's question.
        '''
        return _get_language_prompt_dict().get(self.code, None)

class Language(Enum):
    '''Language enum.'''
    
    Afrikaans = LanguageInfo('af', iso_639_1='af', iso_639_3='afr', microsoft_lang='af-ZA', origin_name='Afrikaans')
    Albanian = LanguageInfo('sq', iso_639_1='sq', iso_639_3='sqi', microsoft_lang='sq-AL',origin_name='Arbëresh')
    Arabic = LanguageInfo('ar', iso_639_1='ar', iso_639_3='ara', microsoft_lang='ar-SA', duckduckgo_lang='xa-ar',origin_name='العربية')
    Armenian = LanguageInfo('hy', iso_639_1='hy', iso_639_3='hye', microsoft_lang='hy-AM',origin_name='Հայերեն')
    Azerbaijani = LanguageInfo('az', iso_639_1='az', iso_639_3='aze', microsoft_lang='az-AZ', aliases=('azeri',),origin_name='Azərbaycanca')
    Basque = LanguageInfo('eu', iso_639_1='eu', iso_639_3='eus', microsoft_lang='eu-ES',origin_name='Euskara')
    Belarusian = LanguageInfo('be', iso_639_1='be', iso_639_3='bel', microsoft_lang='be-BY',origin_name='Беларуская')
    Bengali = LanguageInfo('bn', iso_639_1='bn', iso_639_3='ben', microsoft_lang='bn-BD',origin_name='বাংলা')
    Bokmal = LanguageInfo('nb', iso_639_1='nb', iso_639_3='nob', microsoft_lang='nb-NO',origin_name='Bokmål')
    Bosnian = LanguageInfo('bs', iso_639_1='bs', iso_639_3='bos', microsoft_lang='bs-BA',origin_name='Bosanski')
    Bulgarian = LanguageInfo('bg', iso_639_1='bg', iso_639_3='bul', microsoft_lang='bg-BG', duckduckgo_lang='bg-bg',origin_name='Български')
    Burmese = LanguageInfo('my', iso_639_1='my', iso_639_3='mya', microsoft_lang='my-MM',origin_name='မြန်မာဘာသာ')
    Catalan = LanguageInfo('ca', iso_639_1='ca', iso_639_3='cat', microsoft_lang='ca-ES', duckduckgo_lang='ct-ca',origin_name='Català')
    Croatian = LanguageInfo('hr', iso_639_1='hr', iso_639_3='hrv', microsoft_lang='hr-HR', duckduckgo_lang='hr-hr',origin_name='Hrvatski')
    Czech = LanguageInfo('cs', iso_639_1='cs', iso_639_3='ces', microsoft_lang='cs-CZ', duckduckgo_lang='cz-cs',origin_name='Čeština')
    Danish = LanguageInfo('da', iso_639_1='da', iso_639_3='dan', microsoft_lang='da-DK', duckduckgo_lang='dk-da',origin_name='Danish')
    Dutch = LanguageInfo('nl', iso_639_1='nl', iso_639_3='nld', microsoft_lang='nl-NL', duckduckgo_lang='nl-nl',origin_name='Nederlands')
    English = LanguageInfo('en', iso_639_1='en', iso_639_3='eng', microsoft_lang='en-US', duckduckgo_lang='us-en',origin_name='English')
    Esperanto = LanguageInfo('eo', iso_639_1='eo', iso_639_3='epo', microsoft_lang='eo-001',origin_name='Espéranto')
    Estonian = LanguageInfo('et', iso_639_1='et', iso_639_3='est', microsoft_lang='et-EE', duckduckgo_lang='ee-et',origin_name='Eesti')
    Finnish = LanguageInfo('fi', iso_639_1='fi', iso_639_3='fin', microsoft_lang='fi-FI', duckduckgo_lang='fi-fi',origin_name='Suomi')
    French = LanguageInfo('fr', iso_639_1='fr', iso_639_3='fra', microsoft_lang='fr-FR', duckduckgo_lang='fr-fr',origin_name='Français')
    Ganda = LanguageInfo('lg', iso_639_1='lg', iso_639_3='lug', microsoft_lang='lg-UG',origin_name='Oluganda')
    Georgian = LanguageInfo('ka', iso_639_1='ka', iso_639_3='kat', microsoft_lang='ka-GE',origin_name='ქართული')
    German = LanguageInfo('de', iso_639_1='de', iso_639_3='deu', microsoft_lang='de-DE', duckduckgo_lang='de-de',origin_name='Deutsch')
    Greek = LanguageInfo('el', iso_639_1='el', iso_639_3='ell', microsoft_lang='el-GR', duckduckgo_lang='gr-el',origin_name='Ελληνικά')
    Gujarati = LanguageInfo('gu', iso_639_1='gu', iso_639_3='guj', microsoft_lang='gu-IN',origin_name='ગુજરાતી')
    Hebrew = LanguageInfo('he', iso_639_1='he', iso_639_3='heb', microsoft_lang='he-IL', duckduckgo_lang='il-he',origin_name='עברית')
    Hindi = LanguageInfo('hi', iso_639_1='hi', iso_639_3='hin', microsoft_lang='hi-IN',origin_name='हिन्दी')
    Hungarian = LanguageInfo('hu', iso_639_1='hu', iso_639_3='hun', microsoft_lang='hu-HU', duckduckgo_lang='hu-hu',origin_name='Hungarian')
    Hausa = LanguageInfo('ha', iso_639_1='ha', iso_639_3='hau', microsoft_lang='ha-NG',origin_name='Hausa')
    Icelandic = LanguageInfo('is', iso_639_1='is', iso_639_3='isl', microsoft_lang='is-IS',origin_name='Icelandic')
    Indonesian = LanguageInfo('id', iso_639_1='id', iso_639_3='ind', microsoft_lang='id-ID', duckduckgo_lang='id-id',origin_name='Bahasa Indonesia')
    Irish = LanguageInfo('ga', iso_639_1='ga', iso_639_3='gle', microsoft_lang='ga-IE',origin_name='Gaeilge')
    Italian = LanguageInfo('it', iso_639_1='it', iso_639_3='ita', microsoft_lang='it-IT', duckduckgo_lang='it-it',origin_name='Italiano')
    Japanese = LanguageInfo('ja', iso_639_1='ja', iso_639_3='jpn', microsoft_lang='ja-JP', duckduckgo_lang='jp-jp',origin_name='日本語')
    Kazakh = LanguageInfo('kk', iso_639_1='kk', iso_639_3='kaz', microsoft_lang='kk-KZ',origin_name='Қазақ тілі')
    Korean = LanguageInfo('ko', iso_639_1='ko', iso_639_3='kor', microsoft_lang='ko-KR', duckduckgo_lang='kr-kr',origin_name='한국어')
    Kyrgyz = LanguageInfo('ky', iso_639_1='ky', iso_639_3='kir', microsoft_lang='ky-KG',origin_name='Кыргызча')
    Kinyarwanda = LanguageInfo('rw', iso_639_1='rw', iso_639_3='kin', microsoft_lang='rw-RW',origin_name='Kinyarwanda')
    Kirundi = LanguageInfo('rn', iso_639_1='rn', iso_639_3='run', microsoft_lang='rn-BI',origin_name='Ikirundi')
    Latin = LanguageInfo('la', iso_639_1='la', iso_639_3='lat', microsoft_lang='la-VA',origin_name='Latina')
    Latvian = LanguageInfo('lv', iso_639_1='lv', iso_639_3='lav', microsoft_lang='lv-LV', duckduckgo_lang='lv-lv',origin_name='Latviešu')
    Lithuanian = LanguageInfo('lt', iso_639_1='lt', iso_639_3='lit', microsoft_lang='lt-LT', duckduckgo_lang='lt-lt',origin_name='Lietuvių')
    Macedonian = LanguageInfo('mk', iso_639_1='mk', iso_639_3='mkd', microsoft_lang='mk-MK',origin_name='Македонски')
    Malay = LanguageInfo('ms', iso_639_1='ms', iso_639_3='msa', microsoft_lang='ms-MY', duckduckgo_lang='my-ms',origin_name='Melayu')
    Maori = LanguageInfo('mi', iso_639_1='mi', iso_639_3='mri', microsoft_lang='mi-NZ',origin_name='Māori')
    Marathi = LanguageInfo('mr', iso_639_1='mr', iso_639_3='mar', microsoft_lang='mr-IN',origin_name='मराठी')
    Mongolian = LanguageInfo('mn', iso_639_1='mn', iso_639_3='mon', microsoft_lang='mn-MN',origin_name='Монгол')
    Nepali = LanguageInfo('ne', iso_639_1='ne', iso_639_3='nep', microsoft_lang='ne-NP',origin_name='नेपाली')
    Nynorsk = LanguageInfo('nn', iso_639_1='nn', iso_639_3='nno', microsoft_lang='nn-NO', duckduckgo_lang='no-no',origin_name='Nynorsk')
    Persian = LanguageInfo('fa', iso_639_1='fa', iso_639_3='fas', microsoft_lang='fa-IR',origin_name='فارسی')
    Polish = LanguageInfo('pl', iso_639_1='pl', iso_639_3='pol', microsoft_lang='pl-PL', duckduckgo_lang='pl-pl',origin_name='Polski')
    Portuguese = LanguageInfo('pt', iso_639_1='pt', iso_639_3='por', microsoft_lang='pt-PT', duckduckgo_lang='pt-pt',origin_name='Português')
    Punjabi = LanguageInfo('pa', iso_639_1='pa', iso_639_3='pan', microsoft_lang='pa-IN',origin_name='ਪੰਜਾਬੀ')
    Romanian = LanguageInfo('ro', iso_639_1='ro', iso_639_3='ron', microsoft_lang='ro-RO', duckduckgo_lang='ro-ro',origin_name='Română')
    Russian = LanguageInfo('ru', iso_639_1='ru', iso_639_3='rus', microsoft_lang='ru-RU', duckduckgo_lang='ru-ru',origin_name='Русский')
    Serbian = LanguageInfo('sr', iso_639_1='sr', iso_639_3='srp', microsoft_lang='sr-RS',origin_name='Српски')
    Shona = LanguageInfo('sn', iso_639_1='sn', iso_639_3='sna', microsoft_lang='sn-ZW',origin_name='ChiShona')
    Slovak = LanguageInfo('sk', iso_639_1='sk', iso_639_3='slk', microsoft_lang='sk-SK', duckduckgo_lang='sk-sk',origin_name='Slovenčina')
    Slovene = LanguageInfo('sl', iso_639_1='sl', iso_639_3='slv', microsoft_lang='sl-SI', duckduckgo_lang='sl-sl',origin_name='Slovenski')
    Somali = LanguageInfo('so', iso_639_1='so', iso_639_3='som', microsoft_lang='so-SO',origin_name='Soomaali')
    Sotho = LanguageInfo('st', iso_639_1='st', iso_639_3='sot', microsoft_lang='st-ZA',origin_name='Sesotho')
    Spanish = LanguageInfo('es', iso_639_1='es', iso_639_3='spa', microsoft_lang='es-ES', duckduckgo_lang='es-es',origin_name='Español')
    Swahili = LanguageInfo('sw', iso_639_1='sw', iso_639_3='swa', microsoft_lang='sw-KE',origin_name='Kiswahili')
    Swedish = LanguageInfo('sv', iso_639_1='sv', iso_639_3='swe', microsoft_lang='sv-SE', duckduckgo_lang='se-sv',origin_name='Svenska')
    Tagalog = LanguageInfo('tl', iso_639_1='tl', iso_639_3='tgl', microsoft_lang='tl-PH', duckduckgo_lang='ph-tl',origin_name='Filipino')
    Tamil = LanguageInfo('ta', iso_639_1='ta', iso_639_3='tam', microsoft_lang='ta-IN',origin_name='தமிழ்')
    Telugu = LanguageInfo('te', iso_639_1='te', iso_639_3='tel', microsoft_lang='te-IN',origin_name='తెలుగు')
    Thai = LanguageInfo('th', iso_639_1='th', iso_639_3='tha', microsoft_lang='th-TH', duckduckgo_lang='th-th',origin_name='ไทย')
    Tsonga = LanguageInfo('ts', iso_639_1='ts', iso_639_3='tso', microsoft_lang='ts-ZA', origin_name='Xitsonga')
    Tswana = LanguageInfo('tn', iso_639_1='tn', iso_639_3='tsn', microsoft_lang='tn-ZA', origin_name='Tswana')
    Turkish = LanguageInfo('tr', iso_639_1='tr', iso_639_3='tur', microsoft_lang='tr-TR', duckduckgo_lang='tr-tr', origin_name='Türkçe')
    Ukrainian = LanguageInfo('uk', iso_639_1='uk', iso_639_3='ukr', microsoft_lang='uk-UA', duckduckgo_lang='ua-uk', origin_name='Українська')
    Urdu = LanguageInfo('ur', iso_639_1='ur', iso_639_3='urd', microsoft_lang='ur-PK', origin_name='اردو')
    Uzbek = LanguageInfo('uz', iso_639_1='uz', iso_639_3='uzb', microsoft_lang='uz-UZ', aliases=('uzbek',), origin_name='Oʻzbekcha')
    Vietnamese = LanguageInfo('vi', iso_639_1='vi', iso_639_3='vie', microsoft_lang='vi-VN', duckduckgo_lang='vn-vi', origin_name='Tiếng Việt')
    Welsh = LanguageInfo('cy', iso_639_1='cy', iso_639_3='cym', microsoft_lang='cy-GB', origin_name='Cymraeg')
    Xhosa = LanguageInfo('xh', iso_639_1='xh', iso_639_3='xho', microsoft_lang='xh-ZA', origin_name='isiXhosa')
    Yoruba = LanguageInfo('yo', iso_639_1='yo', iso_639_3='yor', microsoft_lang='yo-NG', origin_name='Yorùbá')
    Zulu = LanguageInfo('zu', iso_639_1='zu', iso_639_3='zul', microsoft_lang='zu-ZA', origin_name='isiZulu')

    # Chinese
    SimplifiedChinese = LanguageInfo('zh-cn', aliases=('zh-hans', 'cmn-hans', 'mandarin', 'putonghua', 'zh_cn'), origin_name='简体中文',
                                     iso_639_1='zh', iso_639_3='cmn', microsoft_lang='zh-Hans', duckduckgo_lang='cn-zh')
    TraditionalChinese = LanguageInfo('zh-tw', aliases=('zh-hant', 'cmn-hant', 'zh', 'zh_tw'), origin_name='繁體中文',
                                      iso_639_1='zh', iso_639_3='cmn', microsoft_lang='zh-Hant', duckduckgo_lang='tw-tzh')
    Cantonese = LanguageInfo('zh-yue', aliases=('yue', 'cantonese'), origin_name='粵語',
                             iso_639_1='zh', iso_639_3='yue', microsoft_lang='zh-HK', duckduckgo_lang='hk-tzh')
    '''Cantonese Chinese(粤语). Note that it doesn't mean traditional Chinese(it can contains simplified chinese).'''

    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        def validator(value):
            if isinstance(value, str):
                if (lang:=cls.Find(value)):
                    return lang
                raise ValueError(f"Cannot find language by name or code `{value}`.")
            return value

        def serializer(value: Self):
            return value.code
            
        dump_schema = core_schema.no_info_after_validator_function(validator, core_schema.any_schema())
        serialize_schema = core_schema.plain_serializer_function_ser_schema(serializer)
        return core_schema.json_or_python_schema(
            json_schema=dump_schema,
            python_schema=dump_schema,
            serialization=serialize_schema,
        )
    
    def __eq__(self, other):
        if isinstance(other, str):
            if (lang:=self.Find(other)):
                return lang == self
        return super().__eq__(other)
    
    def __hash__(self):
        return hash(self.name)
    
    @classmethod
    def __FuzzyMatchDict__(cls)->FuzzyDict["Language"]:
        if '__FuzzyMatchDictCache__' not in cls.__dict__:
            data = {}
            for item in cls:
                data[item.name] = item
                data[item.code] = item
                data[item.iso_639_1] = item
                data[item.iso_639_3] = item
                if item.microsoft_lang:
                    data[item.microsoft_lang] = item
                if item.duckduckgo_lang != 'wt-wt':
                    data[item.duckduckgo_lang] = item
                for alias in item.aliases:
                    data[alias] = item
            cls.__FuzzyMatchDictCache__ = FuzzyDict(data)   # type: ignore
        return cls.__FuzzyMatchDictCache__  # type: ignore
    
    @classmethod
    def Find(cls, code_or_name: "str|Language")->"Language|None":
        '''
        Get language by ISO 639-1/ISO 639-3/language name.
        Return none if not found.
        '''
        if isinstance(code_or_name, cls):
            return code_or_name
        code_or_name = code_or_name.lower().replace('_', '-')   # type: ignore
        if code_or_name == 'zh':
            return cls.TraditionalChinese
        if (e:=cls.__FuzzyMatchDict__().get(code_or_name, None)):
            return e
        return None
    
    if TYPE_CHECKING:
        @property
        @override
        def value(self)->LanguageInfo:...
    
    @property
    def is_chinese(self):
        return self in (Language.SimplifiedChinese, Language.TraditionalChinese, Language.Cantonese)
    
    @property
    def code(self)->str:
        '''
        Code of this language.
        For non-chinese, it follows ISO 639-1 code, e.g. 'en'.
        For Chinese, it follows 'zh-cn'/'zh-tw'/'zh-yue'.
        '''
        return self.value.code
    
    @property
    def origin_name(self)->str:
        '''Origin name of this language, e.g. 'English' for 'en'.'''
        return self.value.origin_name
    
    @property
    def iso_639_1(self)->str:
        '''ISO 639-1 code of this language.'''
        return self.value.iso_639_1
    
    @property
    def iso_639_3(self)->str:
        '''ISO 639-3 code of this language.'''
        return self.value.iso_639_3
    
    @property
    def thanks_for_your_question_text(self)->str|None:
        '''
        `Thanks for your question` in this language, e.g. "谢谢你的提问" when `zh-cn`.
        Note that only some languages have this value.
        This is helpful for chatbot to response to user's question.
        '''
        return self.value.thanks_for_your_question_text
    
    @property
    def language_prompt(self)->str:
        '''
        `Answer in <language>` in this language, e.g. "用中文回答" when `zh-cn`.
        Note that only some languages have this value.
        This is helpful for chatbot to response to user's question.
        '''
        if not (p:=self.value.language_prompt):
            p = self.value.origin_name
        return p
    
    @property
    def microsoft_lang(self):
        '''Microsoft language code of this language, e.g. 'zh-Hans' for Simplified Chinese.'''
        return self.value.microsoft_lang
    
    @property
    def duckduckgo_lang(self)->str:
        '''region code when passing as query to DuckDuckGo'''
        return self.value.duckduckgo_lang
    
    @property
    def aliases(self)->tuple[str, ...]:
        '''aliases of this language.'''
        return self.value.aliases
    
__all__ = ['LanguageInfo', 'Language']


if __name__ == '__main__':
    print(Language.Find('zh-tw'))
    print([l.name for l in Language])