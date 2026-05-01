import re
import builtins
import inspect
from enum import Enum

from dataclasses import dataclass, MISSING
from inspect import _empty
from types import UnionType, NoneType, GenericAlias, get_original_bases
from typing import (
    Any,
    Union,
    Literal,
    Self,
    Final,
    ClassVar,
    Annotated,
    TypeVar,
    overload,
    TypeAlias,
    Callable,
    Protocol,
    ForwardRef,
    TypeVarTuple,
    TypeAliasType,
    no_type_check,
    TYPE_CHECKING,
    Required,
    NotRequired,
    get_args as tp_get_args,
    get_origin as tp_get_origin,
    runtime_checkable,
    _LiteralGenericAlias,  # type: ignore
    _CallableGenericAlias,  # type: ignore
    is_typeddict,
)
from typing_extensions import TypeForm
from pydantic.v1 import BaseModel as BaseModelV1
from pydantic.v1.fields import Undefined as PydanticV1Undefined
from pydantic import BaseModel as BaseModelV2, AliasChoices, create_model, ConfigDict
from pydantic.fields import PydanticUndefined  # type: ignore
from pydantic_core import core_schema

# region types
BasicType: TypeAlias = int | float | str | bool | bytes | list | tuple | dict | set | NoneType
"""Basic type of python, except for complex, range, slice, ellipsis, and types defined in typing module"""

BaseModelType: TypeAlias = BaseModelV1 | BaseModelV2
"""BaseModel type of pydantic, including BaseModelV1 and BaseModelV2"""

type Number = int | float
"""Number type, including int and float"""

@runtime_checkable
class Comparable(Protocol):
    """Comparable protocol, for types that can be compared."""

    def __lt__(self, __other: Any) -> bool: ...
    def __eq__(self, __other: Any) -> bool: ...

@runtime_checkable
class StringLike(Protocol):
    """for types whom has implemented `__str__`"""

    def __str__(self) -> str: ...


__all__ = [
    "BasicType",
    "BaseModelType",
    "Number",
    "Comparable",
    "StringLike",
]
# endregion


@overload
def get_sub_clses[T: type](cls_or_ins: T) -> tuple[T, ...]: ...
@overload
def get_sub_clses[T: object](cls_or_ins: T) -> tuple[type[T], ...]: ...

def get_sub_clses(cls_or_ins):
    """
    Get all sub classes of a class, recursively.
    The class itself will also be included as the first element.
    """
    from .checking import _tidy_type

    cls_or_ins = _tidy_type(cls_or_ins)[0]  # type: ignore

    if not isinstance(cls_or_ins, type):
        cls_or_ins = type(cls_or_ins)
    if not hasattr(cls_or_ins, "__subclasses__"):
        return (cls_or_ins,)
    else:
        sub_clses = cls_or_ins.__subclasses__()
        all_subclses = [cls_or_ins]
        for sub_cls in sub_clses:
            sub_sub_clses = get_sub_clses(sub_cls)
            for sub_sub_cls in sub_sub_clses:
                if sub_sub_cls not in all_subclses:
                    all_subclses.append(sub_sub_cls)
        return tuple(all_subclses)


def getmro(cls: type) -> tuple[type, ...]:
    """
    Get the method resolution order of a class, recursively.
    Different with inspect.getmro, this function will return the original bases of the class(if any),
    i.e. `A[int]` instead of `A`.
    """
    from .checking import _tidy_type

    cls = _tidy_type(cls)[0]  # type: ignore
    try:
        clses = {}

        def insert(cls, depth=0, seen=0):
            nonlocal clses
            if cls in clses:
                if clses[cls][0] > depth:
                    return
                if clses[cls][1] >= seen:
                    return
            clses[cls] = (depth, seen)
            origin = tp_get_origin(cls)
            if origin:
                bases = get_original_bases(origin)
            else:
                bases = get_original_bases(cls)
            for b in bases:
                seen += 1
                insert(b, depth + 1, seen)

        insert(cls)
        return tuple(sorted(clses.keys(), key=lambda x: clses[x][0]))
    except Exception:  # some special types may fail to get mro
        return (cls,)

def get_cls_annotations(
    cls: type | object,
    no_cls_var: bool = False,
    no_final: bool = False,
) -> dict[str, type]:
    """
    Recursively get the annotations of a class, including its base classes.

    Args:
        - `cls`: the class or instance
        - `no_cls_var`: if True, will not include `ClassVar` annotations.
        - `no_final`: if True, will not include `Final` annotations.

    Some special case to note:
    1. type vars will be filled with the actual type arguments if available,
        e.g.
        ```
        class A[T]:
            x: T

        class B(A[int]):...

        get_cls_annotations(B) -> {'x': int}
        ```

    2. empty type alias type will be converted to the real type, e.g.
        ```
        type Int = int

        class A:
            x: Int

        get_cls_annotations(A) -> {'x': int}
        ```
    """
    from .checking import _tidy_type
    
    if isinstance(cls, TypeAliasType):
        cls = cls.__value__
    if cls is object:
        return {}
    
    arg_matches = {}
    origin = tp_get_origin(cls) or cls
    try:
        bases = get_original_bases(origin)  # type: ignore
    except:
        bases = []
    
    type_params = None
    if args := tp_get_args(cls):
        type_params = getattr(origin, "__type_params__", None)
    if not args and (pd_generic_meta:=getattr(origin, "__pydantic_generic_metadata__", None)):
        # special case for pydantic generic models
        args = pd_generic_meta.get("args", None)
        if not type_params and bases and (base_params:=getattr(bases[0], '__parameters__', None)):
            type_params = base_params
    if type_params and args:
        if len(type_params) == len(args):
            if len(type_params) == 1 and isinstance(type_params[0], TypeVarTuple):
                args = tuple([args])
            for t, a in zip(type_params, args):
                arg_matches[t] = a
        
    annos = {}
    for b in bases[::-1]:
        if b is object:
            continue
        annos.update(get_cls_annotations(b, no_cls_var=no_cls_var, no_final=no_final))  # type: ignore
        
    cls_annos = {}
    if not hasattr(cls, "__annotations__"):
        if hasattr(cls, "__origin__") and hasattr(cls, "__args__"):
            # this is a type alias type, e.g. `A[int]`
            cls = cls.__origin__  # type: ignore
            
    for k, v in getattr(cls, "__annotations__", {}).items():
        cls_annos[k] = _tidy_type(v, arg_matches)[0]  # type: ignore
    if not is_typeddict(cls):
        annos.update(cls_annos)  # type: ignore
    else:   # special case, as typeddict will include generic types in its annotations
        for k, v in cls_annos.items():
            if isinstance(v, TypeVar):
                if k in annos:
                    curr = annos[k]
                    if isinstance(curr, TypeVar):
                        annos[k] = v
                    else:
                        ...
                else:
                    annos[k] = v
            else:
                annos[k] = v
    
    tidied = {}
    for k, v in annos.items():
        t = _tidy_type(v, arg_matches)
        try:
            t = t[0]  # type: ignore
        except TypeError:
            ...
        t_origin = tp_get_origin(t)
        if t_origin is ClassVar and no_cls_var:
            continue
        if t_origin is Final and no_final:
            continue
        tidied[k] = t
    return tidied


def get_origin(t: Any, self=None, return_t_if_no_origin: bool = False) -> type | None:  # type: ignore
    """
    Return the origin type of the type hint.
    Different to typing.get_origin, this function will convert some special types to their real origin type,

    Args:
        `self`: if provided, for type = `Self`, it will return the `self`.
        `return_t_if_no_origin`: if True, will return the type itself if no origin is found.

    e.g.
        * int|str -> Union                  (the origin typing.get_origin will return UnionType, which is not easy to do comparison)
        * ForwardRef('A') -> ForwardRef     (the origin typing.get_origin will return None, which is not correct)
        * _empty -> Any
    """
    from .checking import _tidy_type

    tt = _tidy_type(t)
    try:
        t = tt[0]  # type: ignore
    except TypeError:
        t = tt

    if t == _empty:
        return Any  # type: ignore
    if isinstance(t, ForwardRef):
        return ForwardRef
    if t == Self:
        if self is not None:
            if isinstance(self, type):
                return type(self)
            else:
                return self
        else:
            return Self

    origin = tp_get_origin(t)
    if origin in (UnionType, Union):
        return Union  # type: ignore

    if return_t_if_no_origin and origin is None:
        return t
    return origin


def get_args(t, str_to_type: bool = True) -> tuple[Any, ...]:
    """
    Return the args of the type hint.
    Different to typing.get_args, this function will convert some special types to their real args,

    e.g.
        * ForwardRef('A') -> ('A',)     (the origin typing.get_args will return (), which is not correct)

    if `str_to_type` is True, string type args will try to be converted to their real type,
    e.g. list['int'] -> (int, ) instead of ('int', )
    """
    from .checking import _tidy_type

    tt = _tidy_type(t)
    try:
        t = tt[0]  # type: ignore
    except TypeError:
        t = tt

    if isinstance(t, ForwardRef):
        r = (t.__forward_arg__,)
    else:
        r = tp_get_args(t)
    if str_to_type:
        converted_r = []
        for arg in r:
            if isinstance(arg, str):
                converted_r.append(_tidy_type(arg)[0])  # type: ignore
            else:
                converted_r.append(arg)
    return r


def get_cls_name(
    cls: Any,
    with_module_name: bool = False,
    with_generic: bool = True,
    no_qualname: bool = False,
    ellipsis_to_dots: bool = False,
) -> str:
    """
    Return the pure class name, without module name. e.g. 'A' instead of 'utils.xxx....A
    If `__qualname__` is not available, it will use `__name__` instead.
    For generic class, it will return the class with its type arguments, e.g. `List[int]`.

    Args:
        cls: the class to be get name.
        with_module_name: if True, will return the class name with module name, e.g. 'utils.xxx....A'
                         This is only available for non-builtin classes.
        with_generic: if True, will return the class name with its type arguments, e.g. `List[int]`,
                        otherwise, will return the class name without type arguments, e.g. `List`.
        no_qualname: if True, when the class is under another class, it will return the pure
                    class name only, without the parent class name.
        ellipsis_to_dots: if False, will return 'Ellipsis' instead of '...' for `...` type.

    Note:
        1. if `cls` is a string, it will return the string itself, instead of `str`.
        2. For Literal, if `with_generic` is False, it will return `Literal` instead of `Literal[...]`.
        3. For Union, if `with_generic` is False, it will return `Union` instead of `Union[...]`.
        4. For ForwardRef, the return value will be the forward ref string itself.
    """
    from .checking import _tidy_type, _save_isinstance

    raw_cls = cls
    module = get_module_name(cls) if hasattr(cls, "__module__") else None
    cls = _tidy_type(cls)[0]  # type: ignore
    cls_origin = get_origin(cls)
    
    if not module and cls != raw_cls:
        module = get_module_name(cls.__module__) if hasattr(cls, "__module__") else None
    
    if with_generic and _save_isinstance(cls, GenericAlias):
        main_cls_name = get_cls_name(cls.__origin__, with_module_name, False)
        arg_names = []
        for arg in cls.__args__:
            arg_name = get_cls_name(arg, with_module_name, with_generic)
            if arg_name.lower() == "ellipsis":
                arg_name = "..."
            arg_names.append(arg_name)
        return f"{main_cls_name}[{', '.join(arg_names)}]"

    if _save_isinstance(cls, str):
        # seems to be a class name already
        return cls

    elif _save_isinstance(cls, TypeVar):
        n = "TypeVar" if not with_module_name else "typing.TypeVar"
        if with_generic:
            n += f"[{cls.__name__}"
            if constraints := cls.__constraints__:
                n += ": (" + ", ".join(get_cls_name(c, with_module_name, with_generic) for c in constraints) + ")]"
            else:
                n += "]"
        return n

    elif _save_isinstance(cls, UnionType) or cls_origin is Union:
        # Union
        if not with_generic:
            return "Union"
        else:
            name_str = ", ".join(get_cls_name(arg, with_module_name, with_generic) for arg in cls.__args__)
            name_str = f"Union[{name_str}]"
            if module and with_module_name:
                return f"{module}.{name_str}"
            return name_str

    elif _save_isinstance(cls, ForwardRef):
        # ForwardRef
        if with_module_name and cls.__forward_module__:
            if module:
                return f"{module}.{cls.__forward_arg__}"
            return f"{cls.__forward_module__}.{cls.__forward_arg__}"
        return cls.__forward_arg__

    elif _save_isinstance(cls, _LiteralGenericAlias):
        # Literal
        def get_arg_str(a):
            if type(a) == "str":
                return f"'{a}'"
            return str(a)

        full_str = "Literal[" + ", ".join(get_arg_str(a) for a in cls.__args__) + "]"
        if module and with_module_name:
            return f"{module}.{full_str}"
        return full_str

    elif _save_isinstance(cls, _CallableGenericAlias):
        # Callable
        if not with_generic:
            return "Callable"
        params, ret = get_args(cls)
        if params == Ellipsis:
            params_str = "..."
        else:
            params_str = ", ".join(get_cls_name(p, with_module_name, with_generic) for p in params)
        ret_str = get_cls_name(ret, with_module_name, with_generic, no_qualname, ellipsis_to_dots)
        full_str = f"Callable[[{params_str}], {ret_str}]"
        if module and with_module_name:
            return f"{module}.{full_str}"
        return full_str

    elif get_origin(cls) in (Final, ClassVar, Annotated):
        return get_cls_name(
            get_args(cls)[0],
            with_module_name,
            with_generic,
            no_qualname,
            ellipsis_to_dots,
        )

    elif cls == Callable:
        if module and with_module_name:
            return f"{module}.Callable"
        return "Callable"

    elif cls == Ellipsis:
        if ellipsis_to_dots:
            return "..."
        return "Ellipsis"

    elif not _save_isinstance(cls, type):
        # seems giving an object
        cls = type(cls)

    if hasattr(cls, "__qualname__"):
        n = cls.__qualname__
    elif hasattr(cls, "__name__"):
        n = cls.__name__
    elif hasattr(cls, "__repr__"):
        n = cls.__repr__().split(".")[-1].split("<")[0].split("[")[0].split("(")[0].split("{")[0]
    else:
        n = str(cls).split(".")[-1].split("<")[0].split("[")[0].split("(")[0].split("{")[0]

    if not with_generic and "[" in n:
        n = n.split("[")[0]
    if no_qualname:
        n = n.split(".")[-1]

    if with_module_name and not is_builtin(cls):
        if module:
            return f"{module}.{n}"
        try:
            module_name = get_module_name(cls)
        except:
            module_name = ""
        if module_name:
            return f"{module_name}.{n}"
    return n


@no_type_check
def get_module_name(t: Any) -> str:
    """
    Get the proper module name of the type.
    This is useful when running scripts directly for debugging,

    e.g. you define a class in `utils.xxx....`, but the module will shows '__main__' when running the script directly.
    Class will be redefined by python as '__main__.A', which is different from 'utils.xxx....A'.
    By using this function, you could get the proper module name `utils.xxx....` instead of `__main__`
    """
    from .checking import _get_module_name

    return _get_module_name(t)


MAX_MRO_DISTANCE = 999


def get_mro_distance(cls: Any, super_cls: type | str | None) -> int:
    """
    Return the distance of cls to super_cls in the mro.
    If cls is not a subclass of super_cls, return 999.

    Args:
        cls: the class to be checked.
        super_cls: the super class to be checked. It could also be special types like Union, Optional, ForwardRef, etc.
    """
    from .checking import _tidy_type, check_type_is

    cls = _tidy_type(cls)
    super_cls = _tidy_type(super_cls)[0]  # type: ignore

    if cls is None and super_cls is None:
        return 0
    elif cls is None or super_cls is None:
        return MAX_MRO_DISTANCE

    if cls == Any:
        cls = object
    if super_cls == Any:
        super_cls = object

    if not check_type_is(cls, super_cls):
        return MAX_MRO_DISTANCE

    origin = get_origin(super_cls)
    type_args = get_args(super_cls)

    if origin == Union and type_args:
        return min(get_mro_distance(cls, t) for t in type_args)

    elif origin == Literal and type_args:
        try:
            return (
                type_args == get_args(cls) and get_origin(cls) == Literal
            )  # e.g. Literal[1, 2, 3] == Literal[1, 2, 3] -> True
        except:
            return MAX_MRO_DISTANCE
    elif (origin == ForwardRef and type_args) or isinstance(super_cls, str):
        cls_mro_names = [get_cls_name(c) for c in getmro(cls)]
        try:
            return cls_mro_names.index(super_cls if isinstance(super_cls, str) else type_args[0])
        except ValueError:  # not found
            return MAX_MRO_DISTANCE
    else:
        try:
            return getmro(cls).index(super_cls)
        except ValueError:  # not found
            return MAX_MRO_DISTANCE


def is_builtin(obj: Any) -> bool:
    """check if an object is a builtin function or type."""
    from .checking import _tidy_type

    obj = _tidy_type(obj)[0]  # type: ignore
    if not (r := inspect.isbuiltin(obj)):
        cls_name = get_cls_name(obj)
        r = hasattr(builtins, cls_name)
    return r


@overload
def getattr_raw(obj: Any, attr_name: str) -> Any: ...
@overload
def getattr_raw(obj: Any, attr_name: str, raise_err: Literal[True]) -> Any: ...
@overload
def getattr_raw(obj: Any, attr_name: str, raise_err: Literal[False]) -> "Any | Empty": ...

def getattr_raw(obj, attr_name: str, raise_err=True):
    """
    Get the attr object with the given name.
    Different from `getattr`, this method will avoid triggering magic methods, e.g. `__getattr__`,
    `__getattribute__`, `__get__`, etc.
    """
    if not isinstance(obj, type) and hasattr(obj, "__dict__") and attr_name in obj.__dict__:
        return obj.__dict__[attr_name]

    object_type = type(obj) if not isinstance(obj, type) else obj
    all_clses = (*object_type.__bases__, object_type)
    for cls in all_clses[::-1]:
        if hasattr(cls, "__dict__") and attr_name in cls.__dict__:
            return cls.__dict__[attr_name]
    if not raise_err:
        return inspect.Parameter.empty
    raise AttributeError(f"{obj} has no attribute {attr_name}.")


__DocCache__: dict[str, "TypeDoc"] = {}

@dataclass
class TypeDoc:
    """
    Documentation of a type. This dataclass is returned by `type_utils.get_doc` function.
    Apart from `__doc__` of the class, this dataclass also includes:
        - all fields's doc defined with in the class.
        - all methods's doc defined with in the class.
    """

    type_doc: str | None
    """doc of the type"""
    field_docs: dict[str, str]
    """doc of the fields. This field only includes docs for fields who has docstring."""
    attr_docs: dict[str, str]
    """
    doc of the other attrs, including all remaining attrs(properties, methods, ...)
    in this type(except class & fields).
    """
    inner_cls_docs: dict[str, "TypeDoc"]
    """doc of the inner classes. This field only includes docs for inner classes who has docstring."""


__AllCleanedSources__: dict[str, str] = {}

def _get_clean_source(t: type) -> str:
    t_name = get_cls_name(t, with_module_name=True)
    if t_name in __AllCleanedSources__:
        return __AllCleanedSources__[t_name]
    source_lines = [l for l in inspect.cleandoc(inspect.getsource(t)).split("\n") if l.strip()]
    source = "\n".join(source_lines)
    __AllCleanedSources__[t_name] = source
    return source

def get_doc(t: type) -> TypeDoc:
    """
    Try to get detail docs of the given type.
    This method will return a TypeDoc object, which includes:
        - doc of the type (__doc__)
        - doc of the fields
        - doc of inner classes
        - doc of the all other attrs

    NOTE: magic methods/some special internal functions will not be included in the doc,
        e.g. `__signature__`, `__init_subclass__`, `__new__`, `__repr__`, etc...
    """
    from .checking import _save_isinstance

    if _save_isinstance(t, TypeAliasType):
        t_name = f"{get_module_name(t.__module__)}.{t.__name__}"
        if t_name in __DocCache__:
            return __DocCache__[t_name]
        type_doc = None

        # find source file
        try:
            full_doc = get_doc(t.__value__)
            type_alias_doc = TypeDoc(
                type_doc or full_doc.type_doc,
                full_doc.field_docs,
                full_doc.attr_docs,
                full_doc.inner_cls_docs,
            )
        except:
            type_alias_doc = TypeDoc(type_doc, {}, {}, {})
        __DocCache__[t_name] = type_alias_doc
        return type_alias_doc

    if is_builtin(t):
        raise ValueError(f"Cannot get doc of builtin type {t}.")

    type_name = get_cls_name(t, with_module_name=True)
    if type_name in __DocCache__:
        return __DocCache__[type_name]

    full_source = _get_clean_source(t) + "\n"
    for sub_cls in t.__bases__[::-1]:
        if not is_builtin(sub_cls):
            full_source += _get_clean_source(sub_cls) + "\n"
    full_source = re.sub(r"\n\n+", "\n", full_source, flags=re.MULTILINE)
    all_sources_lines = [l for l in full_source.split("\n") if l.strip()]

    type_doc = TypeDoc(inspect.getdoc(t), {}, {}, {})

    gotten_attrs: set[str] = set(
        [
            "__dict__",
            "__dir__",
            "__doc__",
            "__module__",
            "__weakref__",
            "__annotations__",
            "__class__",
            "__delattr__",
            "__dir__",
            "__doc__",
            "__eq__",
            "__format__",
            "__ge__",
            "__getattribute__",
            "__gt__",
            "__hash__",
            "__init__",
            "__init_subclass__",
            "__le__",
            "__lt__",
            "__ne__",
            "__new__",
            "__reduce__",
            "__reduce_ex__",
            "__repr__",
            "__setattr__",
            "__sizeof__",
            "__signature__",
            "_abc_impl",
            "__str__",
            "__subclasshook__",
            "__class_getitem__",
            "__abstractmethods__",
            "__annotations__",
            "__base__",
            "__bases__",
            "__basicsize__",
            "__get_pydantic_schema__",
            "__dictoffset__",
            "__flags__",
            "__itemsize__",
            "__mro__",
            "__name__",
            "__qualname__",
            "__text_signature__",
            "__weakrefoffset__",
            "__abstractmethods__",
            "__getstate__",
        ]
    )
    all_annos = get_cls_annotations(t)

    # get inner methods & classes first.
    for attr_name in dir(t):
        if attr_name.startswith("__") and attr_name.endswith("__"):
            continue
        if attr_name in gotten_attrs or attr_name in all_annos:  # don't get field docs now
            continue
        attr = getattr_raw(t, attr_name, raise_err=False)
        if attr is inspect.Parameter.empty or is_builtin(attr):
            continue
        if isinstance(attr, type):  # inner class
            inner_cls_doc_str = _get_clean_source(attr)
            if inner_cls_doc_str:
                full_source = full_source.replace(inner_cls_doc_str, "")
                # remove inner class's source from type's source
            try:
                inner_type_doc = get_doc(attr)
                type_doc.inner_cls_docs[attr_name] = inner_type_doc
            except Exception:
                continue
        else:  # methods, property, ...
            doc_str = inspect.getdoc(attr)
            if doc_str:
                type_doc.attr_docs[attr_name] = doc_str

    field_line_indices = {}
    for i, line in enumerate(all_sources_lines):
        if m := re.match(r"^[\s\t]*(\w+)[\s\t]*:", line):
            field_name = m.group(1).strip()
            if (field_name in all_annos) and (field_name not in field_line_indices):
                field_line_indices[field_name] = i
    all_field_names = tuple(field_line_indices.keys())

    def get_field_doc(field_name: str):
        if (
            issubclass(t, BaseModelV1)
            and field_name in t.__fields__
            and t.__fields__[field_name].field_info.description
        ):
            return t.__fields__[field_name].field_info.description
        elif issubclass(t, BaseModelV2) and field_name in t.model_fields and t.model_fields[field_name].description:
            return t.model_fields[field_name].description

        if field_name in gotten_attrs or field_name not in field_line_indices:
            return None
        if (field_name_index := all_field_names.index(field_name)) >= (len(all_field_names) - 1):
            till_line_index = len(all_sources_lines)
        else:
            till_line_index = field_line_indices[all_field_names[field_name_index + 1]]
        doc_str = ""
        for i, line_index in enumerate(range(field_line_indices[field_name] + 1, till_line_index)):
            line_str = all_sources_lines[line_index].strip()
            if i == 0:
                if not (line_str.startswith('"""') or line_str.startswith("'''")):
                    return None  # no documentation for this field
                line_str = line_str[3:]
                doc_str += line_str

            if line_str.endswith('"""') or line_str.endswith("'''"):
                if i != 0:
                    doc_str += line_str[:-3]
                else:
                    doc_str = doc_str[:-3]
                break
            doc_str += line_str
        else:
            return None  # doc string not closed
        return doc_str.strip()

    for field_name in all_annos:
        if field_name in gotten_attrs or (field_name.startswith("__") and field_name.endswith("__")):
            continue
        doc_str = get_field_doc(field_name)
        if doc_str:
            type_doc.field_docs[field_name] = doc_str
        gotten_attrs.add(field_name)

    __DocCache__[type_name] = type_doc
    return type_doc


if not TYPE_CHECKING:
    Empty = inspect.Parameter.empty  # type: ignore

# make `inspect.Parameter.empty` serializable in pydantic
if not hasattr(inspect.Parameter.empty, "__get_pydantic_core_schema__"):

    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        from pydantic_core import core_schema

        def validator(value):
            if isinstance(value, dict) and value.get("type") == "empty" and len(value) == 1:
                return inspect.Parameter.empty
            elif value == inspect.Parameter.empty:
                return inspect.Parameter.empty
            raise ValueError(f"Cannot deserialize value `{value}` to empty.")

        def serializer(value):
            if value != Empty:
                return value
            return {
                "type": "empty",
            }

        validate_schema = core_schema.no_info_after_validator_function(validator, core_schema.any_schema())
        serialize_schema = core_schema.plain_serializer_function_ser_schema(serializer, when_used="unless-none")
        return core_schema.json_or_python_schema(
            json_schema=validate_schema,
            python_schema=validate_schema,
            serialization=serialize_schema,
        )

    setattr(
        inspect.Parameter.empty,
        "__get_pydantic_core_schema__",
        __get_pydantic_core_schema__,
    )
inspect.Parameter.empty.__repr__ = lambda *args: "Empty"  # type: ignore

if TYPE_CHECKING:
    type Empty = TypeForm["Empty"]
    """
    Marker object for an empty parameter, for cases that you don't want to use `None` as default value.
    This is actually inspect.Parameter.empty, but some special treatment is done to make it 
    available for easy type hints like `x: T|Empty = Empty`.
    
    Example:
    ```python
    def f(x: int|Empty = Empty):
        ...
    ```
    """


def is_attrs_cls(cls: Any) -> bool:
    """
    Check if a class is an attrs class, i.e. decorated by `@attrs`.
    You can also pass the object of the class, it will automatically convert to the class.
    """
    if not isinstance(cls, type):
        cls = type(cls)
    return hasattr(cls, "__attrs_attrs__")


def is_dataclass(cls: Any) -> bool:
    """
    check if a class is a dataclass, i.e. decorated by `@dataclass`.
    You can also pass the object of the class, it will automatically convert to the class.
    """
    if not isinstance(cls, type):
        cls = type(cls)
    return hasattr(cls, "__dataclass_fields__")


__base_model_fields_aliases__: dict[type, dict[str, tuple[str, ...]]] = {}

def get_pydantic_model_field_aliases(
    cls: type[BaseModelV2] | BaseModelV2 | type[BaseModelV1] | BaseModelV1, field: str
) -> tuple[str, ...]:
    """
    Get all possible values of a field with AliasChoices.
    The first value is the original field name.
    Note: all `AliasPath` object will be ignored.
    """
    if not isinstance(cls, type):
        cls = type(cls)
    if cls not in __base_model_fields_aliases__:
        cache = {}
        __base_model_fields_aliases__[cls] = cache
    else:
        cache = __base_model_fields_aliases__[cls]

    if issubclass(cls, BaseModelV1):
        if field not in cls.__fields__:  # type: ignore
            raise ValueError(f"{field} not found in {cls}")
        if field not in cache:
            model_fields = cls.__fields__
            field_info = model_fields[field]  # type: ignore
            name = field_info.field_info.alias or field
            cache[field] = (name,)

    elif issubclass(cls, BaseModelV2):
        if field not in cls.model_fields:
            raise ValueError(f"{field} not found in {cls}")
        if field not in cache:
            model_fields = cls.model_fields
            field_info = model_fields[field]
            aliases = field_info.validation_alias
            if aliases:
                if isinstance(aliases, str):
                    aliases = (aliases,)
                if isinstance(aliases, AliasChoices):
                    tidied = []
                    for c in aliases.choices:
                        if isinstance(c, str):
                            tidied.append(c)
                    aliases = tuple(tidied)
                else:
                    aliases = (field,)
            else:
                aliases = (field,)
            cache[field] = aliases

    return cache[field]


def pydantic_field_has_default(
    model: type[BaseModelV2] | BaseModelV2 | type[BaseModelV1] | BaseModelV1, field: str
) -> bool:
    """check whether a field in pydantic model has default value or not."""
    from pydantic.v1.fields import Undefined as PydanticUndefinedV1

    if not isinstance(model, type):
        model = type(model)
    if issubclass(model, BaseModelV1):
        field_info = model.__fields__[field]  # will raise error if not found
        if field_info.default == PydanticUndefinedV1 and field_info.default_factory == PydanticUndefinedV1:
            return False
    else:
        field_info = model.model_fields[field]  # will raise error if not found
        if field_info.default == PydanticUndefined and field_info.default_factory == PydanticUndefined:
            return False
    return True


@dataclass
class _DefaultValueConstraints:
    min_length: int | None = None
    max_length: int | None = None
    gt: Number | None = None
    ge: Number | None = None
    lt: Number | None = None
    le: Number | None = None


def _tidy_default_instance_type(t: Any) -> Any:
    from .checking import _tidy_type

    try:
        t = _tidy_type(t)[0]  # type: ignore
    except TypeError:
        t = _tidy_type(t)

    return t


def _unwrap_default_instance_type(t: Any) -> Any:
    t = _tidy_default_instance_type(t)

    while get_origin(t) in (Required, NotRequired, Final, ClassVar):
        args = get_args(t)
        if not args:
            break
        t = args[0]
    return t


def _get_annotation_base_type(t: Any) -> Any:
    t = _unwrap_default_instance_type(t)
    if get_origin(t) is Annotated:
        args = get_args(t)
        if args:
            return _get_annotation_base_type(args[0])
    return t


def _merge_lower_bound(curr: Number | None, candidate: Number | None) -> Number | None:
    if candidate is None:
        return curr
    if curr is None:
        return candidate
    return max(curr, candidate)


def _merge_upper_bound(curr: Number | None, candidate: Number | None) -> Number | None:
    if candidate is None:
        return curr
    if curr is None:
        return candidate
    return min(curr, candidate)


def _apply_constraints_from_obj(constraints: _DefaultValueConstraints, source: Any) -> None:
    if source is None:
        return

    constraints.min_length = _merge_lower_bound(
        constraints.min_length,
        getattr(source, 'min_length', getattr(source, 'min_len', None)),
    )
    constraints.max_length = _merge_upper_bound(
        constraints.max_length,
        getattr(source, 'max_length', getattr(source, 'max_len', None)),
    )
    constraints.gt = _merge_lower_bound(constraints.gt, getattr(source, 'gt', None))
    constraints.ge = _merge_lower_bound(constraints.ge, getattr(source, 'ge', None))
    constraints.lt = _merge_upper_bound(constraints.lt, getattr(source, 'lt', None))
    constraints.le = _merge_upper_bound(constraints.le, getattr(source, 'le', None))


def _get_default_value_constraints(t: Any) -> _DefaultValueConstraints:
    constraints = _DefaultValueConstraints()
    tidied_t = _unwrap_default_instance_type(t)
    origin = get_origin(tidied_t)
    if origin is Annotated:
        args = get_args(tidied_t)
        if args:
            _apply_constraints_from_obj(constraints, args[0])
            for meta in args[1:]:
                _apply_constraints_from_obj(constraints, meta)
        return constraints

    _apply_constraints_from_obj(constraints, tidied_t)
    return constraints


def _validate_default_value[T](t: TypeForm[T], value: Any) -> T:
    from .convertors import get_pydantic_type_adapter
    from .checking import check_value_is

    try:
        return get_pydantic_type_adapter(t).validate_python(value)  # type: ignore[arg-type]
    except Exception:
        if check_value_is(value, t):
            return value
        raise


def _try_call_no_args(factory: Callable[..., Any]) -> Any:
    try:
        return factory()
    except TypeError as e:
        raise TypeError(f'Cannot call default factory {factory} without arguments.') from e


def _is_type_subclass(t: Any, parent: type) -> bool:
    try:
        return issubclass(t, parent)
    except TypeError:
        return False


def _is_string_annotation(t: Any) -> bool:
    tidied_t = _get_annotation_base_type(t)
    return _is_type_subclass(tidied_t, str)


def _is_number_annotation(t: Any) -> bool:
    tidied_t = _get_annotation_base_type(t)
    return _is_type_subclass(tidied_t, (int, float)) and not _is_type_subclass(tidied_t, bool)


def _build_string_candidate(label: str, constraints: _DefaultValueConstraints) -> str:
    candidate = label
    if constraints.max_length is not None:
        if constraints.max_length < 0:
            raise ValueError(f'Invalid max_length constraint: {constraints.max_length}')
        candidate = candidate[: constraints.max_length]
    if constraints.min_length is not None:
        if constraints.max_length is not None and constraints.min_length > constraints.max_length:
            raise ValueError(
                f'Conflicting string length constraints: min_length={constraints.min_length}, '
                f'max_length={constraints.max_length}'
            )
        if len(candidate) < constraints.min_length:
            candidate = candidate + ('x' * (constraints.min_length - len(candidate)))
    return candidate


def _build_string_default[T](
    label: str,
    t: TypeForm[T],
    validator: Callable[[Any], Any] | None = None,
) -> T:
    constraints = _get_default_value_constraints(t)
    seen = set()
    candidates: list[str] = []
    validate = validator or (lambda value: _validate_default_value(t, value))

    base_label = label or 'value'
    candidates.append(_build_string_candidate(base_label, constraints))
    candidates.append(_build_string_candidate('x', constraints))

    if constraints.min_length is not None and constraints.min_length > 0:
        candidates.append(_build_string_candidate('x' * constraints.min_length, constraints))
        candidates.append(_build_string_candidate('0' * constraints.min_length, constraints))
    else:
        candidates.extend(['', 'x', '0'])

    last_error: Exception | None = None
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return validate(candidate)
        except Exception as e:
            last_error = e
    raise TypeError(f'Cannot create a valid default string for {t}.') from last_error


def _build_numeric_default[T](
    t: TypeForm[T],
    *,
    prefer_float: bool = False,
    validator: Callable[[Any], Any] | None = None,
) -> T:
    constraints = _get_default_value_constraints(t)
    validate = validator or (lambda value: _validate_default_value(t, value))
    base: float
    if constraints.ge is not None:
        base = float(constraints.ge)
    elif constraints.gt is not None:
        base = float(constraints.gt) + (0.5 if prefer_float else 1.0)
    else:
        base = 0.0

    if constraints.le is not None and base > float(constraints.le):
        base = float(constraints.le)
    if constraints.lt is not None and base >= float(constraints.lt):
        base = float(constraints.lt) - (0.5 if prefer_float else 1.0)

    candidates: list[float] = [base, 0.0, 1.0, -1.0]
    seen = set()
    last_error: Exception | None = None
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            if prefer_float:
                value = float(candidate)
            else:
                if int(candidate) != candidate:
                    continue
                value = int(candidate)
            return validate(value)
        except Exception as e:
            last_error = e
    raise TypeError(f'Cannot create a valid default numeric value for {t}.') from last_error


def _get_first_example_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        if value:
            return value[0]
        return PydanticUndefined
    return value


def _get_pydantic_v2_field_default_value(field: Any) -> Any:
    if field.examples:
        example = _get_first_example_value(field.examples)
        if example is not PydanticUndefined:
            return example
    if isinstance(field.json_schema_extra, dict):
        if 'example' in field.json_schema_extra:
            return field.json_schema_extra['example']
        if 'examples' in field.json_schema_extra:
            example = _get_first_example_value(field.json_schema_extra['examples'])
            if example is not PydanticUndefined:
                return example
    if field.default is not PydanticUndefined:
        return field.default
    if field.default_factory not in (None, PydanticUndefined):
        try:
            return field.get_default(call_default_factory=True)
        except TypeError:
            return _try_call_no_args(field.default_factory)
    return PydanticUndefined


def _get_pydantic_v1_field_default_value(field: Any) -> Any:
    extra = getattr(field.field_info, 'extra', {}) or {}
    if 'example' in extra:
        return extra['example']
    if 'examples' in extra:
        example = _get_first_example_value(extra['examples'])
        if example is not PydanticV1Undefined:
            return example
    if getattr(field, 'required', False):
        if field.default_factory not in (None, PydanticV1Undefined):
            return _try_call_no_args(field.default_factory)
        return PydanticV1Undefined
    if field.default is not PydanticV1Undefined:
        return field.default
    if field.default_factory not in (None, PydanticV1Undefined):
        return _try_call_no_args(field.default_factory)
    return PydanticV1Undefined


def _validate_pydantic_v2_field_value(field: Any, value: Any) -> Any:
    return _validate_default_value(field.rebuild_annotation(), value)


def _validate_pydantic_v1_field_value(field: Any, value: Any) -> Any:
    validated, err = field.validate(value, {}, loc=field.alias or field.name)
    if err is not None:
        raise TypeError(f'Invalid default value for field `{field.name}`: {err}')
    return validated


def _get_pydantic_payload_key(model_cls: type, field_name: str) -> str:
    aliases = get_pydantic_model_field_aliases(model_cls, field_name)
    if not aliases:
        return field_name
    return aliases[0]


def _create_pydantic_v2_default_instance(model_cls: type[BaseModelV2], active_type_ids: set[int]) -> BaseModelV2:
    payload: dict[str, Any] = {}
    alias_payload: dict[str, Any] = {}

    for field_name, field in model_cls.model_fields.items():
        value = _get_pydantic_v2_field_default_value(field)
        if value is PydanticUndefined:
            field_type = field.rebuild_annotation()
            if _is_string_annotation(field_type):
                value = _build_string_default(field_name, field_type)
            elif _is_number_annotation(field_type):
                value = _build_numeric_default(
                    field_type,
                    prefer_float=_is_type_subclass(_get_annotation_base_type(field_type), float),
                )
            else:
                try:
                    value = _create_type_default_instance_impl(field_type, active_type_ids)
                except Exception as e:
                    raise TypeError(
                        f'Cannot create default value for pydantic field `{field_name}` of {model_cls}.',
                    ) from e
        value = _validate_pydantic_v2_field_value(field, value)
        payload[field_name] = value
        alias_payload[_get_pydantic_payload_key(model_cls, field_name)] = value

    try:
        return model_cls.model_validate(payload)
    except Exception:
        return model_cls.model_validate(alias_payload)


def _create_pydantic_v1_default_instance(model_cls: type[BaseModelV1], active_type_ids: set[int]) -> BaseModelV1:
    payload: dict[str, Any] = {}
    alias_payload: dict[str, Any] = {}

    for field_name, field in model_cls.__fields__.items():  # type: ignore[attr-defined]
        value = _get_pydantic_v1_field_default_value(field)
        if value is PydanticV1Undefined:
            field_type = getattr(field, 'outer_type_', field.annotation)
            if _is_string_annotation(field_type):
                value = _build_string_default(
                    field_name,
                    field_type,
                    validator=lambda data: _validate_pydantic_v1_field_value(field, data),
                )
            elif _is_number_annotation(field_type):
                value = _build_numeric_default(
                    field_type,
                    prefer_float=_is_type_subclass(_get_annotation_base_type(field_type), float),
                    validator=lambda data: _validate_pydantic_v1_field_value(field, data),
                )
            else:
                try:
                    value = _create_type_default_instance_impl(field_type, active_type_ids)
                except Exception as e:
                    raise TypeError(
                        f'Cannot create default value for pydantic field `{field_name}` of {model_cls}.',
                    ) from e
        value = _validate_pydantic_v1_field_value(field, value)
        payload[field_name] = value
        alias_payload[_get_pydantic_payload_key(model_cls, field_name)] = value

    try:
        return model_cls.parse_obj(payload)
    except Exception:
        return model_cls.parse_obj(alias_payload)


def _get_dataclass_field_alias(field: Any) -> str | None:
    metadata = getattr(field, 'metadata', None)
    if not metadata:
        return None

    for key in ('alias', 'validation_alias', 'serialization_alias'):
        value = metadata.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, AliasChoices):
            for choice in value.choices:
                if isinstance(choice, str):
                    return choice
        if isinstance(value, (tuple, list)):
            for item in value:
                if isinstance(item, str):
                    return item
    return None


def _create_dataclass_default_instance(model_cls: type, active_type_ids: set[int]) -> Any:
    kwargs: dict[str, Any] = {}
    for field_name, field in model_cls.__dataclass_fields__.items():  # type: ignore[attr-defined]
        if not field.init:
            continue

        if field.default is not MISSING:
            value = field.default
        elif field.default_factory is not MISSING:
            value = _try_call_no_args(field.default_factory)
        else:
            field_type = field.type
            if _is_string_annotation(field_type):
                alias_name = _get_dataclass_field_alias(field) or field_name
                value = _build_string_default(alias_name, field_type)
            else:
                try:
                    value = _create_type_default_instance_impl(field_type, active_type_ids)
                except Exception as e:
                    raise TypeError(
                        f'Cannot create default value for dataclass field `{field_name}` of {model_cls}.',
                    ) from e
        kwargs[field_name] = value
    return model_cls(**kwargs)


def _create_typed_dict_default_instance(td_cls: type, active_type_ids: set[int]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    required_keys = set(getattr(td_cls, '__required_keys__', set(td_cls.__annotations__.keys())))
    for field_name, field_type in td_cls.__annotations__.items():
        if field_name not in required_keys:
            continue
        try:
            result[field_name] = _create_type_default_instance_impl(field_type, active_type_ids)
        except Exception as e:
            raise TypeError(
                f'Cannot create default value for TypedDict field `{field_name}` of {td_cls}.',
            ) from e
    return result


def _create_type_default_instance_impl(t: Any, active_type_ids: set[int]) -> Any:
    t = _unwrap_default_instance_type(t)
    added_to_stack = False
    t_id = id(t)

    if t_id in active_type_ids:
        raise TypeError(f'Recursive type detected while creating default instance for {t}.')
    active_type_ids.add(t_id)
    added_to_stack = True

    try:
        if t is Any:
            return None
        if t in (None, NoneType):
            return None

        if isinstance(t, TypeVar):
            if t.__bound__ is not None:
                return _create_type_default_instance_impl(t.__bound__, active_type_ids)
            if t.__constraints__:
                last_error: Exception | None = None
                for sub_t in t.__constraints__:
                    try:
                        return _create_type_default_instance_impl(sub_t, active_type_ids)
                    except Exception as e:
                        last_error = e
                raise TypeError(f'Cannot create default value for constrained TypeVar {t}.') from last_error
            raise TypeError(f'Cannot create default value for unconstrained TypeVar {t}.')

        origin = get_origin(t)
        args = get_args(t)

        if origin is Annotated:
            base_t = args[0]
            if _is_string_annotation(base_t):
                return _build_string_default('value', t)
            if _is_number_annotation(base_t):
                return _build_numeric_default(
                    t,
                    prefer_float=_is_type_subclass(_get_annotation_base_type(base_t), float),
                )
            base_value = _create_type_default_instance_impl(base_t, active_type_ids)
            return _validate_default_value(t, base_value)

        if is_typeddict(t):
            return _create_typed_dict_default_instance(t, active_type_ids)

        if _is_type_subclass(t, BaseModelV2):
            return _create_pydantic_v2_default_instance(t, active_type_ids)
        if _is_type_subclass(t, BaseModelV1):
            return _create_pydantic_v1_default_instance(t, active_type_ids)

        if is_dataclass(t):
            return _create_dataclass_default_instance(t, active_type_ids)

        if origin is Literal:
            if not args:
                raise TypeError(f'Literal {t} has no values.')
            return args[0]

        if _is_type_subclass(t, Enum):
            try:
                return next(iter(t))
            except StopIteration as e:
                raise TypeError(f'Enum {t} has no values.') from e

        if origin is Union:
            non_none_args = [arg for arg in args if _unwrap_default_instance_type(arg) not in (None, NoneType)]
            if len(non_none_args) == 1 and len(non_none_args) != len(args):
                try:
                    return _create_type_default_instance_impl(non_none_args[0], active_type_ids)
                except Exception:
                    return None

            last_error: Exception | None = None
            for arg in args:
                if _unwrap_default_instance_type(arg) in (None, NoneType):
                    continue
                try:
                    return _create_type_default_instance_impl(arg, active_type_ids)
                except Exception as e:
                    last_error = e
            if any(_unwrap_default_instance_type(arg) in (None, NoneType) for arg in args):
                return None
            raise TypeError(f'Cannot create default value for Union {t}.') from last_error

        if t is bool:
            return False

        if t is str:
            return ''
        if _is_type_subclass(t, str):
            return _build_string_default('value', t)

        if t is int:
            return 0
        if _is_type_subclass(t, int) and not _is_type_subclass(t, bool):
            return _build_numeric_default(t, prefer_float=False)

        if t is float:
            return 0.0
        if _is_type_subclass(t, float):
            return _build_numeric_default(t, prefer_float=True)

        if origin in (dict, builtins.dict) or t is dict:
            if len(args) == 2:
                try:
                    key = _create_type_default_instance_impl(args[0], active_type_ids)
                    value = _create_type_default_instance_impl(args[1], active_type_ids)
                    return _validate_default_value(t, {key: value})
                except Exception:
                    return {}
            return {}

        if origin in (list, builtins.list) or t is list:
            if len(args) == 1:
                try:
                    item = _create_type_default_instance_impl(args[0], active_type_ids)
                    return _validate_default_value(t, [item])
                except Exception:
                    return []
            return []

        if origin in (set, builtins.set) or t is set:
            if len(args) == 1:
                try:
                    item = _create_type_default_instance_impl(args[0], active_type_ids)
                    return _validate_default_value(t, {item})
                except Exception:
                    return set()
            return set()

        if origin in (frozenset, builtins.frozenset) or t is frozenset:
            if len(args) == 1:
                try:
                    item = _create_type_default_instance_impl(args[0], active_type_ids)
                    return _validate_default_value(t, frozenset((item,)))
                except Exception:
                    return frozenset()
            return frozenset()

        if origin in (tuple, builtins.tuple) or t is tuple:
            if len(args) == 2 and args[1] is Ellipsis:
                try:
                    item = _create_type_default_instance_impl(args[0], active_type_ids)
                    return _validate_default_value(t, (item,))
                except Exception:
                    return tuple()
            if args:
                if len(args) <= 10:
                    try:
                        values = tuple(_create_type_default_instance_impl(arg, active_type_ids) for arg in args)
                        return _validate_default_value(t, values)
                    except Exception:
                        return tuple()
                return tuple()
            return tuple()

        try:
            return t()
        except Exception as e:
            raise TypeError(f'Cannot create default instance for type {t}.') from e
    finally:
        if added_to_stack:
            active_type_ids.discard(t_id)


def create_type_default_instance[T](t: TypeForm[T]) -> T:
    """Create a best-effort default instance for the given type.

    The function recursively inspects pydantic models, dataclasses, union types,
    literals, enums, generic containers, and a few constrained annotations.
    If no valid default instance can be produced, an exception will be raised.
    """
    return _create_type_default_instance_impl(t, set())


def create_pydantic_core_schema[T](
    validator: Callable[[Any], T], 
    serializer: Callable[[T], BasicType] | None = None,
    schema_model: type[BaseModelV1]|type[BaseModelV2]|None = None,
):
    """
    Alias of `core_schema.json_or_python_schema` for pydantic v2.
    NOTE: this function should only be used under a `__get_pydantic_core_schema__` classmethod.
    
    Example:
    ```python
    from pydantic import BaseModel
    from utils.common.type_utils.type_helpers import create_pydantic_core_schema
    
    class A:
        x: int
        y: str
    
        @classmethod
        def __get_pydantic_core_schema__(cls, source, handler):
            class ASchema(BaseModel):
                x: int
                y: str
                
            return create_pydantic_core_schema(
                validator=lambda data: (A(x=data["x"], y=data["y"]) if isinstance(data, dict) else data),
                serializer=lambda a: {"x": a.x, "y": a.y},
                schema_model=ASchema,
            )
    ```
    """
    validate_schema = core_schema.no_info_after_validator_function(validator, core_schema.any_schema())  # type: ignore
    if serializer is not None:
        serialize_schema = core_schema.plain_serializer_function_ser_schema(serializer)  # type: ignore
    else:
        serialize_schema = None
    if schema_model:
        if issubclass(schema_model, BaseModelV1):
            fields = {}
            for f in schema_model.__fields__.values():
                if f.default != PydanticV1Undefined:
                    fields[f.name] = (f.type_, f.default)
                else:
                    fields[f.name] = f.type_
            v2_config_keys = set(ConfigDict.__annotations__.keys())
            origin_configs = {k:v for k,v in schema_model.__config__.__dict__.items() if not k.startswith("_")}
            configs = {k: v for k, v in origin_configs.items() if k in v2_config_keys}
            configs = ConfigDict(**configs)
            v2_model = create_model(schema_model.__name__, __config__=configs, **fields)    
            json_schema = v2_model.__pydantic_core_schema__
        elif issubclass(schema_model, BaseModelV2):
            json_schema = schema_model.__pydantic_core_schema__
        else:
            raise ValueError(f"`schema_model` must be a pydantic BaseModel class, got {schema_model}.")
    else:
        json_schema = validate_schema
    return core_schema.json_or_python_schema(
        json_schema=json_schema,  # type: ignore
        python_schema=validate_schema,  # type: ignore
        serialization=serialize_schema,  # type: ignore
    )


__all__.extend(
    [
        "get_origin",
        "get_args",
        "get_cls_name",
        "get_mro_distance",
        "get_module_name",
        "get_sub_clses",
        "get_cls_annotations",
        "is_builtin",
        "get_doc",
        "TypeDoc",
        "getattr_raw",
        "Empty",
        "getmro",
        "is_attrs_cls",
        "is_dataclass",
        "get_pydantic_model_field_aliases",
        "pydantic_field_has_default",
        "create_type_default_instance",
        "create_pydantic_core_schema",
    ]
)