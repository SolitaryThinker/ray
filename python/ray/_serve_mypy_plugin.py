from typing import Callable, Optional, Type as PyType
import sys

from mypy.plugin import Plugin, AttributeContext
from mypy.types import Type, Instance, AnyType, TypeOfAny, CallableType
from mypy.nodes import TypeInfo, FuncDef, SymbolTableNode
from mypy.subtypes import find_member

class ServePlugin(Plugin):
    def get_attribute_hook(
        self, fullname: str
    ) -> Optional[Callable[[AttributeContext], Type]]:
        if (fullname.startswith("ray.serve.handle.DeploymentHandle.") or 
            fullname.startswith("ray.serve.handle._DeploymentHandleBase.")):
            return deployment_handle_attribute_hook
        return None

def plugin(version: str) -> PyType[Plugin]:
    return ServePlugin

def lookup_member(type_info: TypeInfo, name: str) -> Optional[SymbolTableNode]:
    for base in type_info.mro:
        sym = base.names.get(name)
        if sym:
            return sym
    return None

def get_default_attr_type(ctx: AttributeContext) -> Type:
    try:
        return ctx.default_attr_type
    except AttributeError:
        return AnyType(TypeOfAny.from_error)

def deployment_handle_attribute_hook(ctx: AttributeContext) -> Type:
    # Check if we are dealing with DeploymentHandle
    if not isinstance(ctx.type, Instance):
        return get_default_attr_type(ctx)

    # If the attribute is already defined on DeploymentHandle, use it.
    if ctx.type.type.get(ctx.context.name):
        return get_default_attr_type(ctx)

    # Check that we have exactly one type argument (the deployment class T)
    if len(ctx.type.args) != 1:
        return get_default_attr_type(ctx)

    deployment_type = ctx.type.args[0]
    if not isinstance(deployment_type, Instance):
        return get_default_attr_type(ctx)

    method_name = ctx.context.name
    sym = lookup_member(deployment_type.type, method_name)
    # sym = find_member(deployment_type.type, method_name, subtype=deployment_type.type)
    
    if not sym:
        return get_default_attr_type(ctx)

    node = sym.node
    if isinstance(node, FuncDef):
        func_type = node.type
        if isinstance(func_type, CallableType):
            ret_type = func_type.ret_type
            
            is_generator = False
            target_type = ret_type

            if isinstance(ret_type, Instance):
                fullname = ret_type.type.fullname
                if fullname in (
                    "typing.Generator",
                    "typing.Iterator",
                    "typing.AsyncGenerator",
                    "typing.AsyncIterator",
                    "collections.abc.Generator",
                    "collections.abc.Iterator",
                    "collections.abc.AsyncGenerator",
                    "collections.abc.AsyncIterator",
                ):
                    is_generator = True
                    if ret_type.args:
                        target_type = ret_type.args[0]
                    else:
                        target_type = AnyType(TypeOfAny.from_another_any, source_any=ret_type)
            
            # Use short names since we'll look up in module directly
            if is_generator:
                short_name = "_DeploymentGeneratorMethod"
            else:
                short_name = "_DeploymentMethod"
            
            module_name = "ray.serve.handle"

            try:
                # Look up the helper type in the module
                if module_name in ctx.api.modules:
                    mod = ctx.api.modules[module_name]
                    sym = mod.names.get(short_name)
                    if sym and sym.node and isinstance(sym.node, TypeInfo):
                        return Instance(sym.node, [target_type])
                
                # Fallback to Any if not found (avoids crash)
                return AnyType(TypeOfAny.from_error)

            except Exception:
                return AnyType(TypeOfAny.from_error)

    return get_default_attr_type(ctx)
