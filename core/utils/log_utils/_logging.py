import logging
import inspect

from math import log2
from typing import TYPE_CHECKING, Any, Sequence

if not TYPE_CHECKING:
    logging.addLevelName(5, "VERBOSE")
    logging.addLevelName(100, "SUCCESS")
logging.VERBOSE = 5     # type: ignore
logging.SUCCESS = 100   # type: ignore

from logging import Logger as _Logger
from pydantic import BaseModel

# region logger
class Logger(_Logger):
    def verbose(self, msg, *args, **kwargs):
        if self.isEnabledFor(5):
            self._log(5, msg, args, **kwargs)
            
    def success(self, msg, *args, **kwargs):
        if self.isEnabledFor(100):
            self._log(100, msg, args, **kwargs)
            
_curr_logger_cls = logging.getLoggerClass()
if not issubclass(_curr_logger_cls, _Logger):   # 只在默认logger类不是自定义Logger时才设置, 防止覆盖已有的自定义Logger类
    logging.setLoggerClass(Logger)

def get_logger(name: str) -> Logger:
    logger = logging.getLogger(name)
    if not isinstance(logger, Logger):
        logger.__class__ = Logger
    return logger   # type: ignore
# endregion logger

DEFAULT_MAX_LOG_LEN = 1024
MAX_LOG_FORMAT_RECURSION = 8
DEFAULT_HIDING_KEYS = ('apikey', 'password', 'secret', 'token', 'access_token', 'refresh_token', 'auth_token',
                       'authorization', 'cookie', 'cookies', 'client_secret',)
_tidy_sensitive_keys = lambda k: k.lower().replace('-', '').replace('_', '').replace(' ', '').strip()

def _hide_sensitive_fields_for_log(v, sensitive_keys: set[str]):
    if v and v!=inspect.Parameter.empty:   # prevent None/False/empty...
        if isinstance(v, str):
            show_len = int(log2(len(v)))
            if show_len <=1:
                show_len = 0
            if show_len:
                return v[:show_len] + '...' + v[-show_len:]  # hide the middle part of the string
            else:
                return '...'  # hide all the string
        elif isinstance(v, dict):
            tidied = {}
            for vk, vv in v.items():
                vk_str = str(vk)
                if _tidy_sensitive_keys(vk_str) in sensitive_keys:
                    tidied[vk] = _hide_sensitive_fields_for_log(vv, sensitive_keys)
                else:
                    tidied[vk] = vv
            return tidied
        elif isinstance(v, (list, tuple, set)):
            original_type = type(v)
            tidied = [_hide_sensitive_fields_for_log(item, sensitive_keys) for item in v]
            return original_type(tidied)  # keep the original type
        else:
            return v
    return v

def shorten_data_for_log(data: str, max_len: int|None=DEFAULT_MAX_LOG_LEN):
    '''
    Shorten the data for log.
    If the data is too long, it will be cut to the max length.
    '''
    if max_len is not None and len(data) > max_len:
        data = data[:max_len//2 - 3] + '...' + data[-max_len//2:]
    return data

_empty = object()  # a unique object to represent empty value

def format_data_for_log(
    data: Any,
    detail_mode:bool = False,
    max_len:int|None = DEFAULT_MAX_LOG_LEN,
    try_hiding_sensitive:bool = False,
    sensitive_keys: Sequence[str] = DEFAULT_HIDING_KEYS,
    max_recuse:int = MAX_LOG_FORMAT_RECURSION,
    _recurse:int = 0,
    _sensitive_keys: set[str]|None = None,
)->str:
    '''
    Since sometimes printing data is too long for review,
    this method will format the data to a more readable format.
    
    Args:
        - data: the data to be formatted. It can be any type.
        - detail_mode: if True, the inner data of the origin data will be shown. Otherwise the formatted data will be more short.
        - max_len: the max length of the formatted data. If the formatted data is longer than this, it will be cut.
        - try_hiding_sensitive: if True, the sensitive data will be hidden. This is only effective when
                               secrets exists in dictionary or object attributes with the keys in `sensitive_keys`.
        - sensitive_keys: the keys that will be considered as sensitive data. This is only effective when `try_hiding_sensitive` is True.
                        Keys will be compared in case-insensitive & no hyphen.
        - max_recuse: the max recursion depth for formatting data. If the data is too deep, it will be cut.
    '''
    if _recurse > max_recuse:
        return "..."
    
    if _sensitive_keys is None:
        _sensitive_keys = set([_tidy_sensitive_keys(k) for k in sensitive_keys])
    
    data_str = ""
    if isinstance(data, dict):
        data_str += "{"
        for k, v in data.items():
            simplified_k = _tidy_sensitive_keys(str(k))
            if try_hiding_sensitive and simplified_k in _sensitive_keys:
                v = _hide_sensitive_fields_for_log(v, _sensitive_keys)
            data_str += f"{k}: "
            formatted = format_data_for_log(v, detail_mode=detail_mode, max_len=max_len, max_recuse=max_recuse, 
                                            _recurse=_recurse+1, _sensitive_keys=_sensitive_keys)
            if (not detail_mode) or (_recurse>0):
                formatted = shorten_data_for_log(formatted, max_len=max_len)
            data_str += f"{formatted}, "
        data_str += "}"
    elif isinstance(data, BaseModel):
        # dump manually, to avoid triggering pydantic's own __repr__ which may cause recursion or too much details
        data_str += f"{data.__class__.__name__}("
        for k in data.__class__.model_fields:
            v = getattr(data, k, _empty)
            if v is _empty:
                continue
            simplified_k = _tidy_sensitive_keys(str(k))
            if try_hiding_sensitive and simplified_k in _sensitive_keys:
                v = _hide_sensitive_fields_for_log(v, _sensitive_keys)
            data_str += f"{k}="
            formatted = format_data_for_log(v, detail_mode=detail_mode, max_len=max_len, max_recuse=max_recuse, 
                                            _recurse=_recurse+1, _sensitive_keys=_sensitive_keys)
            if (not detail_mode) or (_recurse>0):
                formatted = shorten_data_for_log(formatted, max_len=max_len)
            data_str += f"{formatted}, "
        data_str += ")"
    elif isinstance(data, (list, tuple, set)):
        data_str += "["
        for v in data:
            formatted = format_data_for_log(v, detail_mode=detail_mode, max_len=max_len, max_recuse=max_recuse, 
                                            _recurse=_recurse+1, _sensitive_keys=_sensitive_keys)
            if not detail_mode or (_recurse>0):
                formatted = shorten_data_for_log(formatted, max_len=max_len)
            data_str += f"{formatted}, "
        data_str += "]"
    elif isinstance(data, str):
        if not detail_mode or (_recurse>0):
            data = shorten_data_for_log(data, max_len=max_len)
        data_str = data
    else:
        try:
            data_str = repr(data)
        except:
            data_str = f'<{type(data).__name__} object>'
        if not detail_mode or (_recurse>0):
            data_str = shorten_data_for_log(data_str, max_len=max_len)
    return data_str.replace('\n', ' ').strip()


__all__ = [
    'Logger', 'get_logger',
    'format_data_for_log', 'shorten_data_for_log',
]