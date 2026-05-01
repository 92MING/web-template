import os
import sys
import glob
import shutil
import logging
import hashlib
import subprocess
import importlib.util

from pathlib import Path
from types import ModuleType
from typing import Sequence

if os.name != 'nt':
    _TEMP_DIR = os.getenv('TMPDIR', '/tmp')
    _CACHE_DIR = os.path.join(_TEMP_DIR, ".cache")
else:
    _TEMP_DIR = os.getenv('TEMP', '/tmp')
    _CACHE_DIR = os.path.join(_TEMP_DIR, "cache")

_logger = logging.getLogger('cython-builder')

from ..concurrent_utils.file_lock import FileCrossProcessLock as _FallbackLock

class CythonBuilder:
    
    def __init__(self, cache_dir: str | None = None):
        if cache_dir is None:
            self.cache_dir = _CACHE_DIR
        else:
            self.cache_dir = os.path.abspath(cache_dir)
        
        os.makedirs(self.cache_dir, exist_ok=True)
        
        self.build_dir = os.path.join(self.cache_dir, "build")
        self.modules_dir = os.path.join(self.cache_dir, "modules")
        os.makedirs(self.build_dir, exist_ok=True)
        os.makedirs(self.modules_dir, exist_ok=True)
    
    def _get_code_hash(self, code: str) -> str:
        return hashlib.sha256(code.encode('utf-8')).hexdigest()[:16]
    
    def _get_module_path(self, code_hash: str, module_name: str) -> str:
        import platform
        if platform.system() == "Windows":
            ext = ".pyd"
        else:
            ext = ".so"
        return os.path.join(self.modules_dir, f"{module_name}_{code_hash}{ext}")
    
    def _prepare_source_file(self, code: str, code_hash: str, module_name: str) -> str:
        source_file = os.path.join(self.build_dir, f"{module_name}_{code_hash}.pyx")
        with open(source_file, 'w', encoding='utf-8') as f:
            f.write(code)
        return source_file
    
    def _compile_cython(self, source_file: str, module_name: str, code_hash: str, include_dirs: list[str]|None=None) -> str:
        print(f'Compiling Cython module `{module_name}`...')
        try:
            from Cython.Build import cythonize
            from setuptools import setup, Extension
        except ImportError:
            raise ImportError("Cython is required: pip install cython")
        
        include_dirs = include_dirs or []
        temp_build_dir = os.path.join(self.build_dir, f"temp_{code_hash}")
        os.makedirs(temp_build_dir, exist_ok=True)
        
        try:
            setup_script = os.path.join(temp_build_dir, "setup.py")
            setup_content = f'''
import sys
import os
from setuptools import setup, Extension
from Cython.Build import cythonize

sys.path.insert(0, r"{os.path.dirname(source_file)}")

extensions = [
    Extension(
        "{source_file.split(os.sep)[-1][:-4]}",
        [r"{source_file}"],
        include_dirs={include_dirs},
    )
]

setup(
    ext_modules=cythonize(
        extensions,
        compiler_directives={{"language_level": 3}},
        quiet=True
    ),
    script_name="setup.py",
    script_args=["build_ext", "--inplace"]
)
'''
            with open(setup_script, 'w', encoding='utf-8') as f:
                f.write(setup_content)
            cmd = [sys.executable, setup_script, "build_ext", "--inplace"]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=temp_build_dir,
                check=False
            )
            
            if result.returncode != 0:
                _logger.error(f"Cython compilation failed: {result.stderr}")
                raise RuntimeError(f"Cython compilation failed: {result.stderr}")
            
            patterns = [
                os.path.join(temp_build_dir, "*.pyd"),  # Windows
                os.path.join(temp_build_dir, "*.so"),   # Unix
                os.path.join(temp_build_dir, "**", "*.pyd"),  
                os.path.join(temp_build_dir, "**", "*.so"),   
            ]
            
            compiled_files = []
            for pattern in patterns:
                compiled_files.extend(glob.glob(pattern, recursive=True))
            
            if not compiled_files:
                for root, dirs, files in os.walk(temp_build_dir):
                    for file in files:
                        if file.endswith(('.pyd', '.so')):
                            compiled_files.append(os.path.join(root, file))
            
            if not compiled_files:
                raise RuntimeError("Cannot find compiled module file")
            
            compiled_file = compiled_files[0]
            final_path = self._get_module_path(code_hash, module_name)
            shutil.copy2(compiled_file, final_path)
            
            return final_path
            
        finally:
            if os.path.exists(temp_build_dir):
                shutil.rmtree(temp_build_dir, ignore_errors=True)
    
    def _load_module(self, module_path: str, module_name: str, code_hash: str) -> ModuleType:
        spec = importlib.util.spec_from_file_location(f"{module_name}_{code_hash}", module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module: {module_path}")
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    
    def _read_source_code(self, source: str | Path) -> tuple[str, str]:
        if isinstance(source, Path):
            if source.is_file():
                with open(source, 'r', encoding='utf-8') as f:
                    code = f.read()
                module_name = source.stem
                return code, module_name
                
            elif source.is_dir():
                code_parts = []
                files = list(source.glob('*.pyx')) + list(source.glob('*.py'))
                
                if not files:
                    raise ValueError(f"No .pyx or .py files found in directory {source}")
                
                for file_path in sorted(files):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        code_parts.append(f"# File: {file_path.name}\n{f.read()}\n")
                
                code = '\n'.join(code_parts)
                module_name = source.name
                return code, module_name
            else:
                raise ValueError(f"Path does not exist: {source}")
                
        elif isinstance(source, str):
            if len(source) < 260 and not '\n' in source and not source.strip().startswith(('def ', 'class ', 'cdef ', 'cpdef ')):
                try:
                    source_path = Path(source)
                    if source_path.is_file():
                        with open(source_path, 'r', encoding='utf-8') as f:
                            code = f.read()
                        module_name = source_path.stem
                        return code, module_name
                        
                    elif source_path.is_dir():
                        code_parts = []
                        files = list(source_path.glob('*.pyx')) + list(source_path.glob('*.py'))
                        
                        if not files:
                            raise ValueError(f"No .pyx or .py files found in directory {source_path}")
                        
                        for file_path in sorted(files):
                            with open(file_path, 'r', encoding='utf-8') as f:
                                code_parts.append(f"# File: {file_path.name}\n{f.read()}\n")
                        
                        code = '\n'.join(code_parts)
                        module_name = source_path.name
                        return code, module_name
                except (OSError, ValueError):
                    pass
            
            # treat as code string
            get_indent = lambda line: len(line) - len(line.lstrip())
            min_indent = 0
            source_lines = source.splitlines()
            for line in source_lines:
                stripped_line = line.lstrip()
                if stripped_line:
                    indent = get_indent(line)
                    if min_indent == 0 or indent < min_indent:
                        min_indent = indent
            if min_indent > 0:
                source = '\n'.join(line[min_indent:] if len(line) >= min_indent else line for line in source_lines)
            return source.strip(), f"module_{hashlib.sha256(source.encode('utf-8')).hexdigest()[:8]}"
        else:
            raise TypeError("code must be a string or Path")
    
    def __call__(
        self, 
        code: str | Path, 
        module_name: str|None=None,
        include_dirs: str|Sequence[str]|None=None
    ) -> ModuleType:
        '''
        Build and load a Cython module from source code or a .pyx/.py file or directory.
        Args:
            code: Cython source code as a string, or path to a .pyx/.py file, or directory containing .pyx/.py files.
            module_name: Optional name for the module. If not provided, a default name will be used.
        '''
        source_code, _module_name = self._read_source_code(code)
        if not module_name:
            module_name = _module_name
        if isinstance(include_dirs, str):
            include_dirs = [include_dirs]
        if include_dirs:
            source_lines = source_code.splitlines()
            start_line_idx = 0
            for idx, line in enumerate(source_lines):
                stripped_line = line.lstrip()
                if stripped_line.startswith('#'):
                    start_line_idx = idx + 1
                else:
                    break
            for inc_dir in include_dirs[::-1]:
                source_lines.insert(start_line_idx, f'sys.path.insert(0, r"{inc_dir}")')
            source_lines.insert(start_line_idx, 'import sys')
            source_code = '\n'.join(source_lines)

        code_hash = self._get_code_hash(source_code)
        
        cached_module_path = self._get_module_path(code_hash, module_name)
        
        if os.path.exists(cached_module_path):
            _logger.debug(f"found cython module cache: {cached_module_path}")
            try:
                return self._load_module(cached_module_path, module_name, code_hash)
            except ImportError:
                # something wrong occurred in loading cached module, rebuild it
                _logger.warning(f"Failed to load cached cython module, rebuilding: {cached_module_path}...")
                
        lock_name = f"cython_build_{code_hash}"
        with _FallbackLock(lock_name):
            if os.path.exists(cached_module_path):
                _logger.debug(f"found cython module cache after waiting: {cached_module_path}")
                module = self._load_module(cached_module_path, module_name, code_hash)

            _logger.info(f"Start building cython module: {module_name} (hash: {code_hash})")

            source_file = self._prepare_source_file(source_code, code_hash, module_name)
            
            try:
                compiled_path = self._compile_cython(source_file, module_name, code_hash, list(include_dirs) if include_dirs else None)
                _logger.debug(f"Cython build finished: {compiled_path}")
                module = self._load_module(compiled_path, module_name, code_hash)
                
            finally:
                try:
                    if os.path.exists(source_file):
                        os.unlink(source_file)
                except Exception as e:
                    _logger.warning(f"Failed to remove temporary source file: {source_file}. Error: {e}")
                        
        return module

    def clear_cache(self):
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir, ignore_errors=True)
        os.makedirs(self.build_dir, exist_ok=True)
        os.makedirs(self.modules_dir, exist_ok=True)

_default_builder = None

def get_default_builder() -> CythonBuilder:
    '''get the default CythonBuilder instance'''
    global _default_builder
    if _default_builder is None:
        _default_builder = CythonBuilder()
    return _default_builder

def clear_default_cache():
    '''clear the cache of the default CythonBuilder instance'''
    return get_default_builder().clear_cache()

def build_cython(
    code: str | Path, 
    module_name: str|None=None,
    include_dirs: str|Sequence[str]|None=None
) -> ModuleType: 
    '''
    Build and load a Cython module from source code or a .pyx/.py file or directory.
    Args:
        code: Cython source code as a string, or path to a .pyx/.py file, or directory containing .pyx/.py files.
        module_name: Optional name for the module. If not provided, a default name will be used.
    '''
    return get_default_builder()(code, module_name, include_dirs)


__all__ = [
    'CythonBuilder',
    'get_default_builder',
    'clear_default_cache',
    'build_cython',    
]

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    def basic_test(clear_cache=False):
        if clear_cache:
            clear_default_cache()
        cython_code = """
        cpdef str say_hello(name: str):
            return f"Hello, {name}!"
        """
        x = build_cython(cython_code)
        print(x.say_hello("World"))
        print('#' * 40)
        
        math_code = """
        cpdef int fast_add(int a, int b):
            return a + b

        cpdef int fast_multiply(int a, int b):
            return a * b
        """
        math_module = build_cython(math_code)
        print(f"5 + 3 = {math_module.fast_add(5, 3)}")
        print(f"5 * 3 = {math_module.fast_multiply(5, 3)}")
        print('#' * 40)
        
        class_code = """
        cdef class Point:
            cdef public double x, y
            
            def __init__(self, double x, double y):
                self.x = x
                self.y = y
            
            cpdef double distance_to(self, Point other):
                return ((self.x - other.x)**2 + (self.y - other.y)**2)**0.5
            
            def __repr__(self):
                return f"Point({self.x}, {self.y})"

        cdef class Point3D(Point):
            cdef public double z

            def __init__(self, double x, double y, double z):
                super().__init__(x, y)
                self.z = z

            cpdef double distance_to_3d(self, Point3D other):
                return ((self.x - other.x)**2 + (self.y - other.y)**2 + (self.z - other.z)**2)**0.5
            
            def __repr__(self):
                return f"Point3D({self.x}, {self.y}, {self.z})"
        """

        m = build_cython(class_code)
        p1 = m.Point(1.0, 2.0)
        p2 = m.Point(4.0, 6.0)
        print(f"Point 1: {p1}")
        print(f"Point 2: {p2}")
        print(f"Distance: {p1.distance_to(p2)}")

        p3d1 = m.Point3D(1.0, 2.0, 3.0)
        p3d2 = m.Point3D(4.0, 6.0, 8.0)
        print(f"3D Point 1: {p3d1}")
        print(f"3D Point 2: {p3d2}")
        print(f"3D Distance: {p3d1.distance_to_3d(other=p3d2)}")

    def test_string_convert():
        code = '''
        # distutils: language=c++
        # cython: boundscheck=False
        # cython: wraparound=False
        # cython: nonecheck=False
        # cython: cdivision=True

        from libc.stdlib cimport malloc, free
        from libc.string cimport strcpy
        from libcpp.vector cimport vector
        
        cdef vector[char*] v
        
        cpdef init():
            cdef str s
            cdef char* c_str
            for s in ['Hello', 'from', 'Cython']:
                c_str = <char*> malloc((len(s) + 1) * sizeof(char))
                strcpy(c_str, s.encode('utf-8'))
                v.push_back(c_str)
        
        cpdef for_print_hello():
            cdef int i
            for i in range(v.size()):
                print(v[i].decode('utf-8'))
        '''
        m = build_cython(code, module_name="string_test")
        m.init()
        m.for_print_hello()

    # basic_test()
    # basic_test(clear_cache=True)
    
    test_string_convert()