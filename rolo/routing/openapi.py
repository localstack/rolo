"""
OpenAPI specification generation from rolo routes.

This module provides utilities to generate OpenAPI 3.1.0 specifications
from registered routes in a rolo Router.
"""

import inspect
import re
import sys
from typing import TYPE_CHECKING, Any, get_args, get_origin

from .router import HTTP_METHODS

if TYPE_CHECKING:
    from .router import Router


def convert_path_to_openapi(werkzeug_path: str) -> str:
    """
    Convert werkzeug path pattern to OpenAPI path pattern.

    Converts path parameters from werkzeug format (e.g., /<id> or /<int:id>)
    to OpenAPI format (e.g., /{id}).

    :param werkzeug_path: Werkzeug path pattern
    :return: OpenAPI path pattern
    """
    # Convert <variable> or <converter:variable> to {variable}
    return re.sub(r"<(?:(\w+):)?(\w+)>", r"{\2}", werkzeug_path)


def extract_path_parameters(werkzeug_path: str) -> list[dict[str, Any]]:
    """
    Extract path parameters from werkzeug path pattern and generate OpenAPI parameter definitions.

    Converts werkzeug path parameters (e.g., /<id> or /<int:id>) into OpenAPI
    parameter objects with appropriate types.

    :param werkzeug_path: Werkzeug path pattern
    :return: List of OpenAPI parameter objects
    """
    # Pattern to match <converter:name> or <name>
    pattern = r"<(?:(\w+):)?(\w+)>"
    matches = re.findall(pattern, werkzeug_path)

    parameters = []
    for converter, name in matches:
        # Map werkzeug converters to OpenAPI types
        param_type = "string"  # default
        if converter in ("int", "float"):
            param_type = "integer" if converter == "int" else "number"

        parameters.append(
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": {"type": param_type},
            }
        )

    return parameters


def _is_typeddict(tp: type) -> bool:
    """
    Check if a type is a TypedDict.

    :param tp: Type to check
    :return: True if the type is a TypedDict
    """
    # TypedDict classes have __annotations__ and either __required_keys__ or __total__
    return (
        hasattr(tp, "__annotations__")
        and hasattr(tp, "__required_keys__")
        and hasattr(tp, "__optional_keys__")
    )


def _python_type_to_json_schema_type(py_type: Any) -> dict[str, Any]:
    """
    Convert a Python type annotation to a JSON Schema type.

    :param py_type: Python type annotation
    :return: JSON Schema type definition
    """
    # Handle None/NoneType
    if py_type is type(None):
        return {"type": "null"}

    # Handle basic types
    if py_type is str:
        return {"type": "string"}
    if py_type is int:
        return {"type": "integer"}
    if py_type is float:
        return {"type": "number"}
    if py_type is bool:
        return {"type": "boolean"}

    # Handle list/List
    origin = get_origin(py_type)
    if origin is list:
        args = get_args(py_type)
        if args:
            item_schema = _python_type_to_json_schema_type(args[0])
            return {"type": "array", "items": item_schema}
        return {"type": "array"}

    # Handle dict/Dict
    if origin is dict:
        return {"type": "object"}

    # Handle TypedDict
    if _is_typeddict(py_type):
        return {"$ref": f"#/components/schemas/{py_type.__name__}"}

    # Default to string for unknown types
    return {"type": "string"}


def _typeddict_to_json_schema(typeddict_class: type) -> dict[str, Any]:
    """
    Convert a TypedDict class to a JSON Schema definition.

    :param typeddict_class: TypedDict class to convert
    :return: JSON Schema object definition
    """
    if not _is_typeddict(typeddict_class):
        raise ValueError(f"{typeddict_class} is not a TypedDict")

    schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    # Add description from docstring if available
    if typeddict_class.__doc__:
        schema["description"] = inspect.cleandoc(typeddict_class.__doc__)

    # Get required and optional keys
    required_keys = getattr(typeddict_class, "__required_keys__", set())

    # Process each field
    for field_name, field_type in typeddict_class.__annotations__.items():
        # Handle NotRequired[T] - unwrap to get the actual type
        # NotRequired is a special form in Python 3.11+
        origin = get_origin(field_type)
        if origin is not None:
            # Check if it's NotRequired by checking the string representation
            # This is more reliable than trying to compare types
            if "NotRequired" in str(origin):
                args = get_args(field_type)
                if args:
                    field_type = args[0]

        schema["properties"][field_name] = _python_type_to_json_schema_type(field_type)

    # Add required array if there are required fields
    if required_keys:
        schema["required"] = sorted(required_keys)

    return schema


def _extract_schemas_from_typeddict(typeddict_class: type) -> dict[str, dict[str, Any]]:
    """
    Recursively extract schemas from a TypedDict and all its nested TypedDicts.

    :param typeddict_class: TypedDict class to extract schemas from
    :return: Dictionary mapping schema names to their JSON Schema definitions
    """
    schemas = {}

    if not _is_typeddict(typeddict_class):
        return schemas

    schema_name = typeddict_class.__name__
    schemas[schema_name] = _typeddict_to_json_schema(typeddict_class)

    # Recursively extract schemas from nested TypedDicts
    for field_type in typeddict_class.__annotations__.values():
        # Unwrap NotRequired if present
        origin = get_origin(field_type)
        if origin is not None and "NotRequired" in str(origin):
            args = get_args(field_type)
            if args:
                field_type = args[0]
                origin = get_origin(field_type)

        # Unwrap list[T] to get T
        if origin is list:
            args = get_args(field_type)
            if args:
                field_type = args[0]

        # Check if nested type is also a TypedDict
        if _is_typeddict(field_type):
            nested_schemas = _extract_schemas_from_typeddict(field_type)
            schemas.update(nested_schemas)

    return schemas


def _extract_return_type_schemas(endpoint: Any) -> dict[str, dict[str, Any]]:
    """
    Extract TypedDict schemas from an endpoint's return type annotation.

    :param endpoint: The endpoint function to inspect
    :return: Dictionary mapping schema names to their JSON Schema definitions
    """
    schemas = {}

    # Get the return type annotation
    sig = inspect.signature(endpoint)
    return_type = sig.return_annotation

    if return_type is inspect.Signature.empty:
        return schemas

    # Unwrap list[T] if present
    origin = get_origin(return_type)
    if origin is list:
        args = get_args(return_type)
        if args:
            return_type = args[0]

    # Check if it's a TypedDict and extract all schemas recursively
    if _is_typeddict(return_type):
        schemas = _extract_schemas_from_typeddict(return_type)

    return schemas


def _extract_request_body_schemas(endpoint: Any, method: str) -> tuple[dict[str, dict[str, Any]], Any]:
    """
    Extract TypedDict schemas from an endpoint's parameter annotations for request body.

    Looks for parameters (excluding 'self' and 'request') with TypedDict annotations.
    Only extracts for methods that typically have request bodies (POST, PUT, PATCH).

    :param endpoint: The endpoint function to inspect
    :param method: HTTP method name
    :return: Tuple of (schemas dict, request_body_type or None)
    """
    schemas = {}
    request_body_type = None

    # Only extract for methods that typically have request bodies
    if method.upper() not in ("POST", "PUT", "PATCH"):
        return schemas, None

    # Get the function signature
    sig = inspect.signature(endpoint)

    # Iterate through parameters (skip 'self' and 'request')
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "request", "cls"):
            continue

        param_type = param.annotation
        if param_type is inspect.Parameter.empty:
            continue

        # Check if it's a TypedDict
        if _is_typeddict(param_type):
            # Extract schemas for this TypedDict and any nested ones
            param_schemas = _extract_schemas_from_typeddict(param_type)
            schemas.update(param_schemas)
            request_body_type = param_type
            # Use the first TypedDict parameter as the request body
            break

    return schemas, request_body_type


def generate_openapi_spec(
    router: "Router", info: dict[str, Any] | None = None, only_with_metadata: bool = False
) -> dict[str, Any]:
    """
    Generate OpenAPI 3.1.0 specification from a Router.
    This function inspects all registered routes in the router and generates
    a complete OpenAPI specification. It extracts metadata from:
    - Route decorators (via _openapi_spec attribute)
    - Function docstrings (for description)
    - Return type annotations (TypedDict classes are converted to schemas)
    :param router: The Router instance to generate spec from
    :param info: Optional OpenAPI info object (title, version, description, etc.)
    :param only_with_metadata: If True, only include routes that have explicit OpenAPI metadata
    :return: Complete OpenAPI specification dict
    """
    if info is None:
        info = {"title": "API", "version": "1.0.0"}

    spec = {"openapi": "3.1.0", "info": info, "paths": {}}
    all_schemas: dict[str, dict[str, Any]] = {}

    # Iterate through all registered rules
    for rule in router.url_map.iter_rules():
        openapi_path = convert_path_to_openapi(rule.rule)

        if openapi_path not in spec["paths"]:
            spec["paths"][openapi_path] = {}

        endpoint = rule.endpoint

        # Get OpenAPI metadata from endpoint if available
        # Check bound method's __func__ first (for instance methods), then the endpoint itself
        openapi_meta = {}
        if hasattr(endpoint, "__func__") and hasattr(endpoint.__func__, "_openapi_spec"):
            openapi_meta = endpoint.__func__._openapi_spec
        elif hasattr(endpoint, "_openapi_spec"):
            openapi_meta = endpoint._openapi_spec

        # Skip routes without OpenAPI metadata if filtering is enabled
        if only_with_metadata and not openapi_meta:
            continue

        # Extract path parameters from the werkzeug route
        path_params = extract_path_parameters(rule.rule)

        # Extract schemas from return type annotations
        endpoint_schemas = _extract_return_type_schemas(endpoint)
        all_schemas.update(endpoint_schemas)

        # Get return type for auto-generating response schema
        sig = inspect.signature(endpoint)
        return_type = sig.return_annotation
        return_type_is_list = False

        if return_type is not inspect.Signature.empty:
            # Check if return type is list[TypedDict]
            origin = get_origin(return_type)
            if origin is list:
                return_type_is_list = True
                args = get_args(return_type)
                if args:
                    return_type = args[0]

        # Process each HTTP method
        # If methods is None, werkzeug allows all methods - default to GET
        methods = rule.methods or HTTP_METHODS
        # Filter out non-OpenAPI methods
        valid_methods = [m for m in methods if m not in ("HEAD", "OPTIONS", "WEBSOCKET")]

        for method in methods:
            # Skip methods that aren't valid OpenAPI operations
            if method in ("HEAD", "OPTIONS", "WEBSOCKET"):
                continue

            # Extract method-specific metadata if openapi_meta has HTTP method keys
            # This handles the @resource decorator pattern where openapi={"get": {...}, "post": {...}}
            method_lower = method.lower()
            if method_lower in openapi_meta:
                # Method-specific metadata (from @resource decorator)
                operation = dict(openapi_meta[method_lower])
            elif any(k.lower() in ("get", "post", "put", "patch", "delete", "head", "options") for k in openapi_meta.keys()):
                # openapi_meta has method keys, but not this method - skip
                continue
            else:
                # Regular metadata (from @route decorator)
                operation = dict(openapi_meta)

            # Handle operationId
            if "operationId" in operation:
                # If there are multiple HTTP methods, prefix operationId with method to ensure uniqueness
                if len(valid_methods) > 1:
                    operation["operationId"] = f"{method.lower()}_{operation['operationId']}"
                # Otherwise, use operationId as-is for single-method routes
            else:
                # Auto-generate operationId from method + path
                # Convert path to a readable identifier
                # Remove leading slash and replace slashes with underscores
                # Keep path parameter names but remove curly braces
                path_id = openapi_path.lstrip("/")
                # Remove curly braces from path parameters: {id} -> id
                path_id = re.sub(r"[{}]", "", path_id)
                # Replace slashes, hyphens with underscores
                path_id = re.sub(r"[/_-]+", "_", path_id).strip("_")
                # Remove leading underscores from _localstack paths
                path_id = path_id.lstrip("_")

                operation["operationId"] = f"{method.lower()}_{path_id}"

            # Auto-generate description from docstring if not provided
            if "description" not in operation and endpoint.__doc__:
                doc = inspect.cleandoc(endpoint.__doc__)
                operation["description"] = doc.split("\n\n")[0]

            # Add path parameters if not already defined and path has parameters
            if path_params and "parameters" not in operation:
                operation["parameters"] = path_params
            elif path_params and "parameters" in operation:
                # Merge path parameters with existing parameters
                # Only add path params that aren't already defined
                existing_param_names = {p.get("name") for p in operation["parameters"]}
                for param in path_params:
                    if param["name"] not in existing_param_names:
                        operation["parameters"].append(param)

            # Auto-generate request body schema from parameter annotations or metadata if not already defined
            if "requestBody" not in operation:
                # First check if requestBodyType is specified in OpenAPI metadata
                request_body_type = operation.pop("requestBodyType", None)

                # If not in metadata, try to extract from parameter annotations
                if not request_body_type:
                    request_body_schemas, request_body_type = _extract_request_body_schemas(
                        endpoint, method
                    )
                    if request_body_type:
                        all_schemas.update(request_body_schemas)

                # If we have a request body type, generate the schema
                if request_body_type:
                    # Extract schemas if not already done
                    if _is_typeddict(request_body_type):
                        type_schemas = _extract_schemas_from_typeddict(request_body_type)
                        all_schemas.update(type_schemas)

                    # Generate requestBody with schema reference
                    operation["requestBody"] = {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{request_body_type.__name__}"}
                            }
                        },
                    }

            # Auto-generate response schema from return type if TypedDict
            if "responses" not in operation:
                if return_type is not inspect.Signature.empty and _is_typeddict(return_type):
                    # Auto-generate response with schema reference
                    schema_ref = {"$ref": f"#/components/schemas/{return_type.__name__}"}

                    if return_type_is_list:
                        response_schema = {"type": "array", "items": schema_ref}
                    else:
                        response_schema = schema_ref

                    operation["responses"] = {
                        "200": {
                            "description": "Successful response",
                            "content": {"application/json": {"schema": response_schema}},
                        }
                    }
                else:
                    # Default response
                    operation["responses"] = {"200": {"description": "Successful response"}}

            spec["paths"][openapi_path][method.lower()] = operation

    # Remove empty paths (paths with no methods) when filtering is enabled
    if only_with_metadata:
        empty_paths = [path for path, methods in spec["paths"].items() if not methods]
        for path in empty_paths:
            del spec["paths"][path]

    # Add schemas to components if any were found
    if all_schemas:
        spec["components"] = {"schemas": all_schemas}

    return spec
