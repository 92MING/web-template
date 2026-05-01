'''
!注意: 此模组已经过全面测试, 确保功能没有问题, 如非必要, 请勿修改此模组的任何代码!
如果启动卡住, 可能是之前你强制退出时留下了过期的端口缓存文件（Windows），请调用 `clear_all_win_cache_files()` 清理它们。
'''
import os
import sys
import logging

if __name__ == '__main__': # for debugging
    logging.basicConfig(level=logging.DEBUG, format='[%(asctime)s][%(levelname)s] %(message)s')
    _proj_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
    sys.path.append(_proj_path)
    __package__ = 'core.utils.concurrent_utils'

import time
import socket
import atexit
import hashlib
import platform
import threading
import multiprocessing.process as process_module
import multiprocessing.managers as manager_module

from pathlib import Path
from pickle import PickleError
from types import FunctionType
from multiprocessing.managers import BaseManager, BaseProxy
from multiprocessing.context import AuthenticationError
from typing import Self, ClassVar, TYPE_CHECKING, Any, Generator, Callable, override

try:
    from .file_lock import FileCrossProcessLock
except ImportError:
    from app.core.utils.concurrent_utils.file_lock import FileCrossProcessLock

_IS_WINDOWS: bool = platform.system() == 'Windows'
_WIN_PORT_MIN: int = 8000
_WIN_PORT_MAX: int = 32768

def _win_cache_dir() -> Path:
    """返回 Windows 下用于存储端口缓存文件的目录。
    可通过环境变量 ``__SHARED_OBJ_DIR__`` 覆盖默认路径，用于测试隔离——
    避免测试进程的 .port 文件与正在运行的 release/dev 服务器冲突。
    """
    override = os.environ.get('__SHARED_OBJ_DIR__')
    if override:
        d = Path(override)
    else:
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home())
        d = base / 'proj-template' / 'shared_obj'
    d.mkdir(parents=True, exist_ok=True)
    return d

def _unix_socket_dir() -> Path:
    """返回 Linux/macOS 下用于存放 Unix-domain socket 的临时目录。"""
    override = os.environ.get('__SHARED_OBJ_DIR__')
    if override:
        d = Path(override)
    else:
        d = Path(os.getenv('TMPDIR', '/tmp')) / 'proj-template-shared-obj'
    d.mkdir(parents=True, exist_ok=True)
    return d

def clear_all_win_cache_files():
    """清理 Windows 下的端口缓存文件。通常在程序启动时调用，以避免过期缓存导致的端口冲突。"""
    if _IS_WINDOWS:
        cache_dir = _win_cache_dir()
        for file in cache_dir.glob('*.port'):
            try:
                file.unlink()
            except OSError:
                pass

def _win_port_file(key: str) -> Path:
    """根据 cache_key 返回对应的端口缓存文件路径。(windows only)"""
    safe = (
        key
        .replace('/', '_').replace('\\', '_')
        .replace(':', '_').replace(' ', '_')
    )
    return _win_cache_dir() / f'{safe}.port'

def _hash_start_port(key: str) -> int:
    """将字符串 key 哈希到 [_WIN_PORT_MIN, _WIN_PORT_MAX) 范围内的起始端口。"""
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return _WIN_PORT_MIN + (h % (_WIN_PORT_MAX - _WIN_PORT_MIN))

def _is_port_free(port: int) -> bool:
    """检测本机 127.0.0.1 上指定端口是否空闲。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False

def _find_free_port(start: int) -> int:
    """从 start 开始向上遍历，返回第一个空闲端口。"""
    port = start
    while port <= 65535:
        if _is_port_free(port):
            return port
        port += 1
    raise RuntimeError('shared_obj: 在 8000-65535 范围内未找到可用端口')

def _win_connect_with_retry(manager: 'BaseManager', port: int, key: str,
                             retries: int = 1, interval: float = 0.1) -> None:
    """等待 manager server 就绪后建立连接，最多重试 retries 次。"""
    for attempt in range(retries):
        try:
            manager.connect()
            _logger.debug(
                'shared_obj: connected to manager for %r at port %d (attempt %d)',
                key, port, attempt + 1,
            )
            return
        except (ConnectionRefusedError, AuthenticationError, OSError):
            if attempt < retries - 1:
                time.sleep(interval)
    raise RuntimeError(
        f'shared_obj: 无法在 {retries} 次尝试内连接到 {key} 的 manager (127.0.0.1:{port})'
    )

_logger = logging.getLogger(__name__)
_all_managers: dict[str, "_Manager"] = dict()

def _close_all_managers():
    for manager in list(_all_managers.values()):
        try:
            manager.close()
        except Exception:
            pass
        
atexit.register(_close_all_managers)

class _Manager(BaseManager):
    _is_creator: bool = False
    # Windows 专用：原始字符串标识符，用于缓存文件命名与锁名称
    _win_cache_key: str = ''

    def __init__(self, address=None, authkey=None, serializer='pickle',
                 ctx=None, *, shutdown_timeout=1.0):
        if not address:
            address = self.__class__.__name__
        if isinstance(address, str):
            if _IS_WINDOWS:
                # Windows 下必须让锁名和 .port 缓存文件与 server instance
                # 一起隔离；否则不同实例会错误共用同一份缓存并互相连到
                # 对方遗留的 manager。
                cache_key = address
                if sk := os.environ.get('__SERVER_INSTANCE_ID__'):
                    cache_key = f'{sk}_{address}'
                self._win_cache_key = cache_key
                address = self._win_resolve_address(cache_key)
            else:
                # Linux/macOS 也按 server instance 隔离 Unix-domain socket，
                # 避免同一台机器上多个 server 实例共用残留 socket。
                if sk := os.environ.get('__SERVER_INSTANCE_ID__'):
                    address = str(_unix_socket_dir() / f'{sk}_{address}')
                else:
                    address = str(_unix_socket_dir() / address)
        super().__init__(address, authkey, serializer, ctx, shutdown_timeout=shutdown_timeout)
        _all_managers[f'{self.__class__.__name__}.{address}'] = self

    # Windows: 根据缓存或哈希确定 (host, port) 地址
    @staticmethod
    def _win_resolve_address(key: str) -> tuple:
        """优先读取缓存文件，否则用哈希计算初始端口。此处仅返回候选地址，
        真正检测可用性在 start() 的锁内完成。"""
        cache_file = _win_port_file(key)
        if cache_file.exists():
            try:
                port = int(cache_file.read_text().strip())
                return ('127.0.0.1', port)
            except (ValueError, OSError):
                pass
        # 没有缓存：哈希到起始端口（start() 内再找可用端口）
        return ('127.0.0.1', _hash_start_port(key))

    @property
    def _lock_name(self):
        prefix = f'{self.__class__.__name__}.'
        # Windows 下用原始字符串 key 命名锁，避免端口未确定时名称不稳定
        if _IS_WINDOWS and self._win_cache_key:
            return f'{prefix}{self._win_cache_key}'
        if self.address:
            if isinstance(self.address, tuple) and len(self.address) == 2:
                return f'{prefix}{self.address[0]}:{self.address[1]}'
            return f'{prefix}{self.address}'
        return prefix

    def start(self):
        if _IS_WINDOWS and self._win_cache_key:
            self._win_start()
        else:
            with FileCrossProcessLock(self._lock_name, default_timeout=4):
                try:
                    self.connect()
                except FileNotFoundError:
                    self._is_creator = True
                    super().start()

    def _win_start(self):
        """Windows 下协调端口分配与 manager server 的启动/连接。"""
        if __name__.endswith('main__'):
            log_method = print
        else:
            log_method = _logger.debug
        key = self._win_cache_key
        cache_file = _win_port_file(key)

        with FileCrossProcessLock(self._lock_name, default_timeout=4):
            if cache_file.exists():
                try:
                    port = int(cache_file.read_text().strip())
                    self._address = ('127.0.0.1', port)  # type: ignore[attr-defined]
                except (ValueError, OSError):
                    cache_file.unlink(missing_ok=True)
                    port = _find_free_port(_hash_start_port(key))
                    self._address = ('127.0.0.1', port)  # type: ignore[attr-defined]
                    cache_file.write_text(str(port))
                    self._is_creator = True
            else:
                port = _find_free_port(_hash_start_port(key))
                self._address = ('127.0.0.1', port)  # type: ignore[attr-defined]
                cache_file.write_text(str(port))
                self._is_creator = True

            if self._is_creator:
                log_method(f'Starting manager for {key} at {self._address} (cached in {cache_file})')
                try:
                    super().start()
                except OSError: # port already used, try to connect in case it's already running by another process
                    try:
                        _win_connect_with_retry(self, port, key)
                        self._is_creator = False
                    except Exception as e:
                        raise RuntimeError(f'Failed to start manager for {key} at port {port} and failed to connect to it as well.') from e
            else:
                log_method(f'Connecting to existing manager for {key} at {self._address} (cached in {cache_file})')
                try:
                    _win_connect_with_retry(self, port, key)
                except (RuntimeError, AuthenticationError):
                    log_method(f'Connection failed for {key} at port {port}, falling back to creator mode')
                    cache_file.unlink(missing_ok=True)
                    port = _find_free_port(_hash_start_port(key))
                    self._address = ('127.0.0.1', port)  # type: ignore[attr-defined]
                    cache_file.write_text(str(port))
                    self._is_creator = True
                    super().start()

    def close(self):
        if self._is_creator:
            try:
                self.shutdown()
            except Exception:
                pass
            if _IS_WINDOWS and self._win_cache_key:
                try:
                    _win_port_file(self._win_cache_key).unlink(missing_ok=True)
                except OSError:
                    pass

    def __del__(self):
        self.close()

    @classmethod
    def register(cls, typeid, model, proxytype, exposed=None,
                 method_to_typeid=None, create_method=True):
        if '_registry' not in cls.__dict__:
            cls._registry = cls._registry.copy()

        exposed = exposed or getattr(proxytype, '_exposed_', None)
        method_to_typeid = method_to_typeid or \
                           getattr(proxytype, '_method_to_typeid_', None)

        if method_to_typeid:
            for key, value in list(method_to_typeid.items()):
                assert type(key) is str, '%r is not a string' % key
                assert type(value) is str, '%r is not a string' % value

        cls._registry[typeid] = (model, exposed, method_to_typeid, proxytype)

        if create_method:
            def temp(self, /, *args, **kwds):
                token, exp = self._create(typeid, *args, **kwds)
                proxy = proxytype(
                    model, args[0], token, self._serializer, manager=self,  # type: ignore
                    authkey=self._authkey, exposed=exp
                    )
                conn = self._Client(token.address, authkey=self._authkey)   
                manager_module.dispatch(conn, None, 'decref', (token.id,))  # type: ignore
                return proxy
            temp.__name__ = typeid
            setattr(cls, typeid, temp)


_proxy_type_cache: dict[tuple, type] = {}
_empty_init = object.__init__
_existing_proxy_attrs = set(
    ('_tls', '_idset', '_token', '_id', '_manager', '_serializer', '_Client', '_owned_by_manager', 
     '_authkey', 'shared_obj_id', '_get_manager', '_get_unknown_attribute') + tuple(dir(BaseProxy))
)

class _BaseProxy(BaseProxy):

    _shared_obj_id: str
    _on_method_call: Callable[[str, tuple, dict[str, Any]], Generator[tuple[tuple, dict[str, Any]], Any, None]]|None = None
    _on_value_gotten: Callable[[str, Any], Any]|None = None
    
    @property
    def shared_obj_id(self)->str:
        return getattr(self, '_shared_obj_id')

    @override
    def _callmethod(self, methodname: str, args: tuple=tuple(), kwds: dict[str, Any]={}):
        method_wrapper = None
        if self._on_method_call is not None:
            method_wrapper = self._on_method_call(methodname, args, kwds)
            args, kwds = next(method_wrapper)
        r = super()._callmethod(methodname, args, kwds)
        if method_wrapper is not None:
            try:
                r = method_wrapper.send(r)
            except StopIteration:
                pass
        return r

    def __getattr__(self, name):
        if not name.startswith('_') and (not name in _existing_proxy_attrs):
            try:
                r = self._callmethod('_get_unknown_attribute', (name,))
                if self._on_value_gotten is not None:
                    r = self._on_value_gotten(name, r)
                return r
            except PickleError as e:
                raise AttributeError(f'Attribute {name} is not serializable and cannot be retrieved from manager process.') from e
        raise AttributeError(f'Attribute {name} not found.')

def _make_proxy_type(name, exposed):
    exposed = tuple(exposed)
    try:
        return _proxy_type_cache[(name, exposed)]
    except KeyError:
        pass

    dic = {}
    for meth in exposed:
        exec('''def %s(self, /, *args, **kwds):
        return self._callmethod(%r, args, kwds)''' % (meth, meth), dic)
    
    ProxyType = type(name, (_BaseProxy,), dic)
    ProxyType._exposed_ = exposed
    _proxy_type_cache[(name, exposed)] = ProxyType
    return ProxyType

def _auto_proxy(cls: type['CrossProcessSharedObject'], id, token, serializer, manager=None, authkey=None,
              exposed=None, incref=True, manager_owned=False):
    if (p:=cls.__Proxies__.get(id, None)) is not None:
        return p
    _Client = manager_module.listener_client[serializer][1] # type: ignore

    if exposed is None:
        conn = _Client(token.address, authkey=authkey)
        try:
            exposed = manager_module.dispatch(conn, None, 'get_methods', (token,))  # type: ignore
        finally:
            conn.close()

    if authkey is None and manager is not None:
        authkey = manager._authkey
    if authkey is None:
        authkey = process_module.current_process().authkey
    
    ProxyType = _make_proxy_type(f'{cls.__name__}Proxy', exposed)
    proxy = ProxyType(token, serializer, manager=manager, authkey=authkey,
                      incref=incref, manager_owned=manager_owned)
    # set proxy attributes
    proxy._isauto = True    # type: ignore
    proxy._shared_obj_id = id  # type: ignore
    if hasattr(cls, '__on_method_call__'):
        on_method_call = getattr(cls, '__on_method_call__')
        if callable(on_method_call):
            proxy._on_method_call = on_method_call  # type: ignore
    if hasattr(cls, '__on_value_gotten__'):
        on_value_gotten = getattr(cls, '__on_value_gotten__')
        if callable(on_value_gotten):
            proxy._on_value_gotten = on_value_gotten  # type: ignore

    cls.__Proxies__[id] = proxy  # type: ignore
    return proxy

_id_func = id

class CrossProcessSharedObject:
    '''
    !注意: CrossProcessSharedObject已经过全面测试确保功能没有问题, 如非必要, 请勿修改任何代码!
    
    `CrossProcessSharedObject` 是一个基类，用于创建可通过 `multiprocessing.Manager` 在多个进程间共享访问的对象。
    共享对象在一个独立进程中创建，当访问方法/属性时，代理（proxy）会将调用转发到 manager 进程并获取返回结果（通过 `pickle` 序列化/反序列化）。
    
    共享对象通过唯一的 `id` 字符串进行标识。当使用相同的 `id` 创建共享对象时，会返回已有的实例而非创建新的。
    注意：即使提供了不同的初始化参数，使用相同 `id` 时对象也不会重新初始化。

    所有不以 `_` 开头的自定义方法会自动暴露给代理。同样，所有不以 `_` 开头的自定义属性也可以通过代理访问。
    注意：只有可被 pickle 序列化的值才能被访问。

    你还可以定义 `__on_method_call__` 和 `__on_value_gotten__` 类方法来自定义代理端的方法调用和值获取行为。

    示例:
    ```python
        class A(CrossProcessSharedObject):
            def __init__(self, id: str, /, x: int, y: int):
                # 你不需要处理 `id`。
                self.x = x
                self.y = y
                self.count = 0
        
            def foo(self, z: int) -> int:
                self.count += 1
                return self.x + self.y + z
            
            def bar(self, x) -> int:
                return self.x + x

            @classmethod
            def __on_method_call__(cls, name: str, args: tuple, kwargs: dict[str, Any]):
                if name == 'bar':
                    x = args[0] if args else kwargs.get('x', 0)
                    r = yield (tuple(), {'x': x + 1})  # 修改参数 x
                    yield r * 2  # 修改返回值
                else:
                    r = yield (args, kwargs)
                    yield r
        
        def worker():
            a = A('shared_a', x=1, y=2)
            print(f'({os.getpid()}) a.foo(3)={a.foo(3)}')
            print(f'({os.getpid()}) a.count={a.count}')
            print(f'({os.getpid()}) a.bar(1)={a.bar(1)} == (1 + 1 + 1)*2 == 6')
            print(f'({os.getpid()}) a.x_plus_y={a.x_plus_y}')
        
        if __name__ == "__main__":
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(5) as executor:
                futures = [executor.submit(worker) for _ in range(5)]
                for future in futures:
                    future.result()
            
        # 最后`count`的值应该是 5，因为每个进程都访问了同一个共享对象实例。
    ```
    '''

    __ManagerClass__: ClassVar[type[_Manager]]              # 仅在当前进程使用
    __Manager__: ClassVar[_Manager]                         # 仅在当前进程使用
    __ManagerLock__: ClassVar[threading.RLock]               # 仅在当前进程使用
    __Proxies__: ClassVar[dict[str, Self]]                  # 仅在当前进程使用
    __Instances__: ClassVar[dict[str, Self]]                # 仅在 manager 进程使用
    __InManagerProcess__: bool = False
    __OriginInit__: FunctionType
    
    if not TYPE_CHECKING:
        def __new__(cls, id: str|None=None, /, **kwargs):
            if not id:
                id = cls.__name__
            if __name__.endswith('main__'):
                log_method = print
            else:
                log_method = _logger.debug
            if cls.__InManagerProcess__:
                lock_key = f'{cls.__name__}_instance_lock_{id}'
                with FileCrossProcessLock(lock_key, default_timeout=4):
                    if (ins:=cls.__Instances__.get(id, None)) is not None:
                        return ins
                    log_method(f'Creating CrossProcessSharedObject of `{cls.__name__}({_id_func(cls)})` in manager process, id=`{id}`(lock_key={lock_key}). Kwargs: {kwargs}. Current instances: {list(cls.__Instances__.keys())}')
                    ins = super().__new__(cls)
                    setattr(ins, '_shared_obj_id', id)
                    cls.__Instances__[id] = ins
                    if cls.__OriginInit__ is not _empty_init:
                        cls.__OriginInit__(ins, id, **kwargs)
                    return ins
            else:
                log_method(f'Getting proxy of `{cls.__name__}` in client process, id=`{id}`. Kwargs: {kwargs}')
                if (p:=cls.__Proxies__.get(id, None)) is not None:
                    return p
                manager = cls._get_manager()
                proxy = manager.__getattribute__(cls.__name__)(id, **kwargs)
                # ``__Proxies__[id]`` 在 ``_auto_proxy`` 中更新
                return proxy
            
        def __init_subclass__(cls, is_subprocess=False) -> None:
            setattr(cls, '__InManagerProcess__', is_subprocess)
            origin_init = getattr(cls, '__init__', _empty_init)
            if origin_init is _empty_init and len(cls.__mro__) >2:
                parent_cls = cls.__mro__[1]
                parent_origin_init = getattr(parent_cls, '__OriginInit__', None)
                if parent_origin_init not in (_empty_init, None):
                    origin_init = parent_origin_init
            setattr(cls, '__OriginInit__', origin_init)
            setattr(cls, '__init__', _empty_init)
            
            if not is_subprocess:
                manager_cls = type(
                    f'{cls.__name__}Manager',
                    (_Manager,),
                    {}
                )
                setattr(cls, '__ManagerClass__', manager_cls)
                setattr(cls, '__ManagerLock__', threading.RLock())
                setattr(cls, '__Proxies__', dict())

                exposes = set(['_get_unknown_attribute',])
                for attr_name in dir(cls):
                    if not attr_name.startswith('_') and not hasattr(CrossProcessSharedObject, attr_name):
                        attr = getattr(cls, attr_name)
                        if isinstance(attr, FunctionType) and not isinstance(attr, staticmethod):
                            exposes.add(attr_name)
                _subprocess_cls = type(
                    cls.__name__,
                    (cls,),
                    {},
                    is_subprocess=True
                )

                # 在 Windows 上，super().start() 会通过 spawn 启动 manager server 子进程。
                # spawn 使用 pickle 传递 Process 对象，要求所有相关类必须可被 pickle。
                # 动态类（type() 创建）默认不在任何模块命名空间，需要手动注册。
                _defining_module = sys.modules.get(cls.__module__) or sys.modules.get('__main__')

                # 注册 manager 类
                manager_cls.__module__ = cls.__module__
                if _defining_module is not None and not hasattr(_defining_module, manager_cls.__name__):
                    setattr(_defining_module, manager_cls.__name__, manager_cls)

                # 注册 subprocess 类（manager server 内实际持有对象的类）
                _subprocess_cls_reg_name = f'_SharedObjServer_{cls.__name__}'
                _subprocess_cls.__name__ = _subprocess_cls_reg_name
                _subprocess_cls.__qualname__ = _subprocess_cls_reg_name
                _subprocess_cls.__module__ = cls.__module__
                if _defining_module is not None and not hasattr(_defining_module, _subprocess_cls_reg_name):
                    setattr(_defining_module, _subprocess_cls_reg_name, _subprocess_cls)

                manager_cls.register(cls.__name__, _subprocess_cls, proxytype=_auto_proxy, exposed=tuple(exposes))
            else:
                setattr(cls, '__Instances__', dict())
         
        @classmethod
        def _get_manager(cls) -> _Manager:
            if (m:=getattr(cls, '__Manager__', None)) is None:
                with cls.__ManagerLock__:
                    if (m:=getattr(cls, '__Manager__', None)) is None:
                        m = cls.__ManagerClass__(cls.__name__)
                        m.start()
                        setattr(cls, '__Manager__', m)
            return m    # type: ignore
        
        def _get_unknown_attribute(self, name: str):
            return getattr(self, name)
        
    else:
        def __init__(self, id: str|None=None, /, **kwargs):
            '''
            根据给定的 ``id`` 创建或获取共享对象实例。
            若留空，则 id = ``cls.__name__``。
            
            ``**kwargs`` 用于传递自定义的初始化参数。
            '''
    
    @property
    def shared_obj_id(self) -> str:
        return getattr(self, '_shared_obj_id')  # type: ignore
    
    if TYPE_CHECKING:
        @classmethod
        def __on_method_call__(cls, name: str, args: tuple, kwargs: dict)->Generator[tuple[tuple, dict[str, Any]], Any, None]: 
            '''
            若定义了此方法，它将在客户端（即代理端）转发调用到 manager 进程之前被调用。
            该方法应为一个生成器，yield 出 (args, kwargs) 元组作为 manager 进程中实际方法调用的参数，
            并可在方法调用后接收 manager 进程的返回值。

            注意：此方法必须是静态方法或类方法。
            '''
            ...

        @classmethod
        def __on_value_gotten__[R](cls, name: str, value: R)->R:
            '''
            若定义了此方法，它将在客户端（即代理端）从 manager 进程获取返回值之后被调用。
            你可以使用此方法来修改返回值。

            注意：此方法必须是静态方法或类方法。
            '''
            ...


__all__ = ['CrossProcessSharedObject', '_close_all_managers', 'clear_all_win_cache_files']

if __name__.endswith('main__'):
    def worker():
        a = A('shared_a', x=1, y=2)
        print(f'({os.getpid()}) a.foo(3)={a.foo(3)}')
        print(f'({os.getpid()}) a.count={a.count}')
        print(f'({os.getpid()}) a.bar(1)={a.bar(1)} == (1 + 1 + 1)*2 == 6')
        print(f'({os.getpid()}) a.x_plus_y={a.x_plus_y}')

    class A(CrossProcessSharedObject):
        def __init__(self, id: str, /, x:int, y:int):
            self.x = x
            self.y = y
            self.count = 0
    
        def foo(self, z: int)->int:
            self.count += 1
            print(f'({os.getpid()}) ({id(self)}) current count: {self.count}')
            return self.x + self.y + z
        
        def bar(self, x)->int:
            return self.x + x
        
        @property
        def x_plus_y(self):
            return self.x + self.y

        @classmethod
        def __on_method_call__(cls, name: str, args: tuple, kwargs: dict[str, Any]):
            if name == 'bar':
                x = args[0] if args else kwargs.get('x', 0)
                r = yield (tuple(), {'x': x + 1})  # modify argument x
                yield r * 2  # modify return value
            else:
                r = yield (args, kwargs)
                yield r
                
if __name__ == "__main__":
    from concurrent.futures import ProcessPoolExecutor
    
    with ProcessPoolExecutor(5) as executor:
        futures = [executor.submit(worker) for _ in range(5)]
        for future in futures:
            future.result()
            
