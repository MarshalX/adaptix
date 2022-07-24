from typing import TYPE_CHECKING, Any, Callable, Tuple, Type, TypeVar, Union

K_contra = TypeVar('K_contra', contravariant=True)
V_co = TypeVar('V_co', covariant=True)
T = TypeVar('T')

Parser = Callable[[Any], V_co]
Serializer = Callable[[K_contra], Any]

TypeHint = Any

VarTuple = Tuple[T, ...]

Catchable = Union[Type[BaseException], VarTuple[Type[BaseException]]]

# https://github.com/python/typing/issues/684#issuecomment-548203158
if TYPE_CHECKING:
    EllipsisType = ellipsis  # pylint: disable=undefined-variable  # noqa: F821
else:
    EllipsisType = type(Ellipsis)
