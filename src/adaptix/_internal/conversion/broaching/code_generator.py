import ast
import itertools
from abc import ABC, abstractmethod
from ast import AST
from collections import defaultdict
from inspect import Signature
from typing import DefaultDict, Mapping, Tuple, Union

from ...code_tools.ast_templater import ast_substitute
from ...code_tools.code_builder import CodeBuilder
from ...code_tools.context_namespace import BuiltinContextNamespace, ContextNamespace
from ...code_tools.utils import get_literal_expr
from ...compat import compat_ast_unparse
from ...model_tools.definitions import DescriptorAccessor, ItemAccessor
from ...special_cases_optimization import as_is_stub
from .definitions import (
    AccessorElement,
    ConstantElement,
    FunctionElement,
    KeywordArg,
    ParameterElement,
    PositionalArg,
    UnpackIterable,
    UnpackMapping,
)

BroachingPlan = Union[
    ParameterElement,
    ConstantElement,
    FunctionElement['BroachingPlan'],
    AccessorElement['BroachingPlan'],
]


class GenState:
    def __init__(self, ctx_namespace: ContextNamespace):
        self._ctx_namespace = ctx_namespace
        self._prefix_counter: DefaultDict[str, int] = defaultdict(lambda: 0)

    def register_next_id(self, prefix: str, obj: object) -> str:
        number = self._prefix_counter[prefix]
        self._prefix_counter[prefix] += 1
        name = f"{prefix}_{number}"
        return self.register_mangled(name, obj)

    def register_mangled(self, base: str, obj: object) -> str:
        if base not in self._ctx_namespace:
            self._ctx_namespace.add(base, obj)
            return base

        for i in itertools.count(1):
            name = f'{base}_{i}'
            if name not in self._ctx_namespace:
                self._ctx_namespace.add(base, obj)
                return name
        raise RuntimeError


class BroachingCodeGenerator(ABC):
    @abstractmethod
    def produce_code(self, closure_name: str, signature: Signature) -> Tuple[str, Mapping[str, object]]:
        ...


class BuiltinBroachingCodeGenerator(BroachingCodeGenerator):
    def __init__(self, plan: BroachingPlan):
        self._plan = plan

    def _create_state(self, ctx_namespace: ContextNamespace) -> GenState:
        return GenState(
            ctx_namespace=ctx_namespace,
        )

    def produce_code(self, closure_name: str, signature: Signature) -> Tuple[str, Mapping[str, object]]:
        builder = CodeBuilder()
        ctx_namespace = BuiltinContextNamespace(occupied=signature.parameters.keys())
        state = self._create_state(ctx_namespace=ctx_namespace)

        ctx_namespace.add('_closure_signature', signature)
        no_types_signature = signature.replace(
            parameters=[param.replace(annotation=Signature.empty) for param in signature.parameters.values()],
            return_annotation=Signature.empty,
        )
        with builder(f'def {closure_name}{no_types_signature}:'):
            body = self._gen_plan_element_dispatch(state, self._plan)
            builder += 'return ' + compat_ast_unparse(body)

        builder += f'{closure_name}.__signature__ = _closure_signature'
        return builder.string(), ctx_namespace.dict

    def _gen_plan_element_dispatch(self, state: GenState, element: BroachingPlan) -> AST:
        if isinstance(element, ParameterElement):
            return self._gen_parameter_element(state, element)
        if isinstance(element, ConstantElement):
            return self._gen_constant_element(state, element)
        if isinstance(element, FunctionElement):
            return self._gen_function_element(state, element)
        if isinstance(element, AccessorElement):
            return self._gen_accessor_element(state, element)
        raise TypeError

    def _gen_parameter_element(self, state: GenState, element: ParameterElement) -> AST:
        return ast.Name(id=element.name, ctx=ast.Load())

    def _gen_constant_element(self, state: GenState, element: ConstantElement) -> AST:
        expr = get_literal_expr(element.value)
        if expr is not None:
            return ast.parse(expr)

        name = state.register_next_id('constant', element.value)
        return ast.Name(id=name, ctx=ast.Load())

    def _gen_function_element(self, state: GenState, element: FunctionElement[BroachingPlan]) -> AST:
        if (
            element.func == as_is_stub
            and len(element.args) == 1
            and isinstance(element.args[0], PositionalArg)
        ):
            return self._gen_plan_element_dispatch(state, element.args[0].element)

        if getattr(element.func, '__name__', None) is not None:
            name = state.register_mangled(element.func.__name__, element.func)
        else:
            name = state.register_next_id('func', element.func)

        args = []
        keywords = []
        for arg in element.args:
            if isinstance(arg, PositionalArg):
                sub_ast = self._gen_plan_element_dispatch(state, arg.element)
                args.append(sub_ast)
            elif isinstance(arg, KeywordArg):
                sub_ast = self._gen_plan_element_dispatch(state, arg.element)
                keywords.append(ast.keyword(arg=arg.key, value=sub_ast))
            elif isinstance(arg, UnpackMapping):
                sub_ast = self._gen_plan_element_dispatch(state, arg.element)
                keywords.append(ast.keyword(value=sub_ast))
            elif isinstance(arg, UnpackIterable):
                sub_ast = self._gen_plan_element_dispatch(state, arg.element)
                args.append(ast.Starred(value=sub_ast, ctx=ast.Load()))
            else:
                raise TypeError

        return ast.Call(
            func=ast.Name(name, ast.Load()),
            args=args,
            keywords=keywords,
        )

    def _gen_accessor_element(self, state: GenState, element: AccessorElement[BroachingPlan]) -> AST:
        target_expr = self._gen_plan_element_dispatch(state, element.target)
        if isinstance(element.accessor, DescriptorAccessor):
            if element.accessor.attr_name.isidentifier():
                return ast_substitute(
                    f'__target_expr__.{element.accessor.attr_name}',
                    target_expr=target_expr,
                )
            return ast_substitute(
                f"getattr(__target_expr__, {element.accessor.attr_name!r})",
                target_expr=target_expr,
            )

        if isinstance(element.accessor, ItemAccessor):
            literal_expr = get_literal_expr(element.accessor.key)
            if literal_expr is not None:
                return ast_substitute(
                    f"__target_expr__[{literal_expr!r}]",
                    target_expr=target_expr,
                )

        name = state.register_next_id('accessor', element.accessor.getter)
        return ast_substitute(
            f"{name}(__target_expr__)",
            target_expr=target_expr,
        )
