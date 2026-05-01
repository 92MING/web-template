from typing import ClassVar, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer

from .type_helpers import get_cls_annotations

def _simplified_str(s: str)->str:
    return s.replace('_', '').lower().replace(' ', '').replace('-', '')

class AdvancedBaseModel(BaseModel):
    '''advance pydantic BaseModel(v2) class with convenient common methods/properties.'''
    
    model_config = ConfigDict(use_attribute_docstrings=True)
    # `use_attribute_docstrings` is set to True by default,
    # for generating documentation with the docstring under fields.
    
    ClassName: ClassVar[str]
    '''alias of `__name__`, for easier access.'''
    FullClassName: ClassVar[str]
    '''alias of `__qualname__`, for easier access.'''
    
    __FieldAliasDict__: ClassVar[dict[str, set[str]]]
    '''{field name: set with all alias(include the name itself)}'''
    
    def __init_subclass__(cls, **kwargs):   
        """
        There are some problems when using __init_subclass__ with pydantic's generic basemodel class
        at the same time. To allow the child cls accept class args during definition, 
        `kwargs` must be added here.
        """
        valid_args = get_cls_annotations(ConfigDict)
        tidied = {}
        for k, v in kwargs.items():
            if k in valid_args:
                tidied[k] = v
        super().__init_subclass__(**tidied)
        cls.ClassName = cls.__name__
        cls.FullClassName = cls.__qualname__
    
    @classmethod
    def ContainsField(cls, field_name: str, fuzzy: bool=False)->str|None:
        '''
        Check if the field_name is a valid field name in the model.
        If `fuzzy` is True, the field_name will be searched in a fuzzy way,
        e.g. `hello_world`==`helloWorld`.
        
        Return the origin field name if found, else return None.
        '''
        for origin_name, field_alias in cls.__FieldAliasDict__.items():
            if field_name in field_alias:
                return origin_name
            if fuzzy:
                fuzzy_field_name = _simplified_str(field_name)
                for alias in field_alias:
                    if _simplified_str(alias) == fuzzy_field_name:
                        return origin_name
        return None
    
    @classmethod
    def GetFieldAliases(cls, field: str)->set[str]:
        if field not in cls.__FieldAliasDict__:
            field_origin_name = cls.ContainsField(field) 
        else:
            field_origin_name = field
        if not field_origin_name:
            raise ValueError(f'Field `{field}` is not found in class `{cls.ClassName}`')
        return cls.__FieldAliasDict__[field_origin_name]
    
    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs):
        cls.__FieldAliasDict__ = {}
        from .type_helpers import get_pydantic_model_field_aliases
        for field in cls.model_fields:
            cls.__FieldAliasDict__[field] = set(get_pydantic_model_field_aliases(cls, field))                
        super().__pydantic_init_subclass__(**kwargs)

class StrictBaseModel(BaseModel):
    '''
    Do NOT use this to mongodb class.
    Make all field strict when validating.
    Note: `use_enum_values` is set to True by default, means that
          enum fields will only contain the values defined in the enum.
    '''
    model_config = ConfigDict(strict=True, use_enum_values=True, use_attribute_docstrings=True)

class ExtraParamsAdvancedBaseModel(AdvancedBaseModel):
    '''
    Special BaseModel which has an `extra_params` field to store unknown parameters
    passing in during model validation, e.g. `{'x': 1}` -> `{'extra_params': {'x': 1}}`.
    
    In serialization, fields in `extra_params` will be moved to the root level,
    e.g. `{'extra_params': {'x': 1}}` -> `{'x': 1}`.
    '''
    
    extra_params: dict[str, Any] = Field(default_factory=dict)
    '''
    Extra params collected during model validation.
    e.g. {'x': 1} -> {'extra_params': {'x': 1}}
    '''
    
    @model_validator(mode='wrap')   # type: ignore
    @classmethod
    def _ExtraParamsAdvanceBaseModelValidator(cls, data, handler):
        if isinstance(data, dict):
            tidied = {}
            extra_params = {}
            for k, v in data.items():
                if (proper_field:=cls.ContainsField(k)):
                    if proper_field == 'extra_params':
                        if not isinstance(v, dict):
                            raise ValueError(f'Field `{proper_field}` should be a dict, but got {type(v)}.') 
                        extra_params.update(v)
                    else:
                        tidied[proper_field] = v
                else:
                    extra_params[k] = v
            tidied['extra_params'] = extra_params
            data = tidied
        data = handler(data)
        return data
    
    @model_serializer(mode='wrap')
    def extra_params_serialize(self, serializer):
        '''
        During model serialization, fields in `extra_params` will be moved to the root level.
        
        NOTE: 
        you MUST call this method in subclass's `@model_serializer` method. 
        Here is an example:
        ```python
        class A(ExtraParamsAdvanceBaseModel):
            @model_serializer(mode='wrap')
            def _serialize(self, serializer):
                data = self.extra_params_serialize(serializer)
                return data
        ```
        '''
        data = serializer(self)
        if isinstance(data, dict):
            extra_args = data.pop('extra_params', {})
            for k, v in extra_args.items():
                if k not in data:
                    data[k] = v
        return data
    
    
__all__ = [
    'AdvancedBaseModel',
    'StrictBaseModel',
    'ExtraParamsAdvancedBaseModel',
    'install_cached_docstring_extractor',
]


# ── Cached docstring extractor ────────────────────────────────────────────────
# Pydantic's ``use_attribute_docstrings=True`` calls
# ``extract_docstrings_from_cls`` for *every* subclass.  That function
# re-reads & re-parses the source file each time, which for thousands of
# generator classes adds up to ~45 s.
#
# ``install_cached_docstring_extractor`` replaces it with a **file-level
# cached** version that reads & parses each .py file only once.

_docstring_patch_installed = False

def install_cached_docstring_extractor() -> None:
    """Install a file-level cached docstring extractor for fast bulk import.
    
    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _docstring_patch_installed
    if _docstring_patch_installed:
        return

    import ast, inspect
    try:
        import pydantic._internal._docs_extraction as _docs_mod
    except ImportError:
        return

    _original_fn = _docs_mod.extract_docstrings_from_cls

    _file_cache: dict[str, dict[int, dict[str, str]]] = {}
    _module_file_cache: dict[str, str | None] = {}

    class _DocstringCollector(ast.NodeVisitor):
        """Walk a full-file AST and collect per-class attribute docstrings."""

        def __init__(self):
            self.results: dict[int, dict[str, str]] = {}

        def visit_Module(self, node: ast.Module):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    self.visit_ClassDef(child)

        def visit_ClassDef(self, node: ast.ClassDef):
            attrs: dict[str, str] = {}
            prev_target: str | None = None
            for child in node.body:
                if isinstance(child, (ast.AnnAssign, ast.Assign)):
                    if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                        prev_target = child.target.id
                    elif isinstance(child, ast.Assign) and len(child.targets) == 1 and isinstance(child.targets[0], ast.Name):
                        prev_target = child.targets[0].id
                    else:
                        prev_target = None
                    continue
                if (
                    prev_target is not None
                    and isinstance(child, ast.Expr)
                    and isinstance(child.value, (ast.Constant, ast.Str))
                ):
                    doc = child.value.value if isinstance(child.value, ast.Constant) else child.value.s
                    if isinstance(doc, str):
                        attrs[prev_target] = inspect.cleandoc(doc)
                    prev_target = None
                    continue
                prev_target = None
                if isinstance(child, ast.ClassDef):
                    self.visit_ClassDef(child)

            self.results[node.lineno] = attrs

    def _cached_extract(cls, use_inspect=False):
        mod_name = cls.__module__
        if mod_name in _module_file_cache:
            src_file = _module_file_cache[mod_name]
        else:
            try:
                src_file = inspect.getfile(cls)
            except (TypeError, OSError):
                src_file = None
            _module_file_cache[mod_name] = src_file

        if src_file is None:
            return _original_fn(cls, use_inspect=use_inspect)

        if src_file not in _file_cache:
            try:
                with open(src_file, 'r', encoding='utf-8') as f:
                    source = f.read()
            except Exception:
                return _original_fn(cls, use_inspect=use_inspect)
            try:
                tree = ast.parse(source)
            except SyntaxError:
                return _original_fn(cls, use_inspect=use_inspect)
            collector = _DocstringCollector()
            collector.visit(tree)
            _file_cache[src_file] = collector.results

        cls_line = getattr(cls, '__firstlineno__', None)
        if cls_line is None:
            try:
                _, cls_line = inspect.getsourcelines(cls)
            except (OSError, TypeError):
                return {}

        return _file_cache[src_file].get(cls_line, {})

    _docs_mod.extract_docstrings_from_cls = _cached_extract
    try:
        import pydantic._internal._fields as _fields_mod
        _fields_mod.extract_docstrings_from_cls = _cached_extract
    except (ImportError, AttributeError):
        pass

    _docstring_patch_installed = True