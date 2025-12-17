"""
Tests for OpenAPI specification generation from rolo routes.
"""

import pytest

from rolo import Request, Response, Router, route
from rolo.routing.openapi import (
    convert_path_to_openapi,
    extract_path_parameters,
    generate_openapi_spec,
)


class TestConvertPathToOpenAPI:
    """Tests for werkzeug to OpenAPI path conversion."""

    def test_simple_path(self):
        assert convert_path_to_openapi("/users") == "/users"

    def test_path_with_variable(self):
        assert convert_path_to_openapi("/users/<id>") == "/users/{id}"

    def test_path_with_typed_variable(self):
        assert convert_path_to_openapi("/users/<int:id>") == "/users/{id}"

    def test_path_with_multiple_variables(self):
        assert convert_path_to_openapi("/users/<user_id>/posts/<post_id>") == "/users/{user_id}/posts/{post_id}"

    def test_path_with_typed_multiple_variables(self):
        assert convert_path_to_openapi("/users/<int:user_id>/posts/<int:post_id>") == "/users/{user_id}/posts/{post_id}"


class TestExtractPathParameters:
    """Tests for path parameter extraction."""

    def test_no_parameters(self):
        """Test path with no parameters."""
        params = extract_path_parameters("/users")
        assert params == []

    def test_single_string_parameter(self):
        """Test path with single untyped parameter (defaults to string)."""
        params = extract_path_parameters("/users/<user_id>")
        assert len(params) == 1
        assert params[0]["name"] == "user_id"
        assert params[0]["in"] == "path"
        assert params[0]["required"] is True
        assert params[0]["schema"]["type"] == "string"

    def test_single_int_parameter(self):
        """Test path with single integer parameter."""
        params = extract_path_parameters("/items/<int:item_id>")
        assert len(params) == 1
        assert params[0]["name"] == "item_id"
        assert params[0]["schema"]["type"] == "integer"

    def test_single_float_parameter(self):
        """Test path with single float parameter."""
        params = extract_path_parameters("/values/<float:value>")
        assert len(params) == 1
        assert params[0]["name"] == "value"
        assert params[0]["schema"]["type"] == "number"

    def test_multiple_parameters(self):
        """Test path with multiple parameters of different types."""
        params = extract_path_parameters("/users/<int:user_id>/posts/<post_id>")
        assert len(params) == 2

        assert params[0]["name"] == "user_id"
        assert params[0]["schema"]["type"] == "integer"

        assert params[1]["name"] == "post_id"
        assert params[1]["schema"]["type"] == "string"


class TestGenerateOpenAPISpec:
    """Tests for OpenAPI specification generation."""

    def test_basic_spec_generation(self):
        """Test generation of basic OpenAPI spec with default info."""
        router = Router()

        @route("/hello", methods=["GET"])
        def hello(request: Request):
            return Response("Hello")

        router.add(hello)

        spec = generate_openapi_spec(router)

        assert spec["openapi"] == "3.1.0"
        assert "info" in spec
        assert spec["info"]["title"] == "API"
        assert spec["info"]["version"] == "1.0.0"
        assert "paths" in spec

    def test_spec_with_custom_info(self):
        """Test generation with custom API info."""
        router = Router()

        @route("/hello", methods=["GET"])
        def hello(request: Request):
            return Response("Hello")

        router.add(hello)

        custom_info = {
            "title": "My API",
            "version": "2.0.0",
            "description": "A test API"
        }

        spec = generate_openapi_spec(router, info=custom_info)

        assert spec["info"]["title"] == "My API"
        assert spec["info"]["version"] == "2.0.0"
        assert spec["info"]["description"] == "A test API"

    def test_spec_with_openapi_metadata(self):
        """Test generation with explicit OpenAPI metadata in route decorator."""
        router = Router()

        @route(
            "/_localstack/chaos/faults",
            methods=["GET"],
            openapi={
                "summary": "Get the current fault configuration",
                "description": "Retrieve the list of currently configured fault rules.",
                "operationId": "get_fault_rules",
                "tags": ["pro", "chaos"],
                "responses": {
                    "200": {
                        "description": "Successful retrieval of current configuration.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/FaultRule"}
                                }
                            }
                        }
                    }
                }
            }
        )
        def get_fault_config(request: Request):
            """Retrieve currently set rules."""
            return Response.for_json([])

        router.add(get_fault_config)

        spec = router.generate_openapi_spec(
            info={"title": "Chaos API", "version": "1.0.0"}
        )

        path_spec = spec["paths"]["/_localstack/chaos/faults"]["get"]

        assert path_spec["summary"] == "Get the current fault configuration"
        assert path_spec["description"] == "Retrieve the list of currently configured fault rules."
        assert path_spec["operationId"] == "get_fault_rules"
        assert path_spec["tags"] == ["pro", "chaos"]
        assert "responses" in path_spec
        assert "200" in path_spec["responses"]

    def test_spec_with_docstring_description(self):
        """Test that docstrings are used as description when no explicit description is provided."""
        router = Router()

        @route("/users", methods=["GET"])
        def get_users(request: Request):
            """
            Get all users.

            This endpoint returns a list of all users in the system.
            """
            return Response.for_json([])

        router.add(get_users)

        spec = generate_openapi_spec(router)
        path_spec = spec["paths"]["/users"]["get"]

        assert path_spec["description"] == "Get all users."

    def test_spec_with_multiple_methods(self):
        """Test spec generation with multiple HTTP methods on same path."""
        router = Router()

        @route("/users", methods=["GET"])
        def get_users(request: Request):
            """Get all users"""
            return Response.for_json([])

        @route("/users", methods=["POST"])
        def create_user(request: Request):
            """Create a new user"""
            return Response.for_json({"id": 1})

        router.add(get_users)
        router.add(create_user)

        spec = generate_openapi_spec(router)

        assert "get" in spec["paths"]["/users"]
        assert "post" in spec["paths"]["/users"]
        assert "Get all users" in spec["paths"]["/users"]["get"]["description"]
        assert "Create a new user" in spec["paths"]["/users"]["post"]["description"]

    def test_spec_with_path_parameters(self):
        """Test spec generation with path parameters."""
        router = Router()

        @route("/users/<user_id>", methods=["GET"])
        def get_user(request: Request, user_id: str):
            """Get a specific user"""
            return Response.for_json({"id": user_id})

        router.add(get_user)

        spec = generate_openapi_spec(router)

        assert "/users/{user_id}" in spec["paths"]
        assert "get" in spec["paths"]["/users/{user_id}"]

    def test_spec_excludes_head_and_options(self):
        """Test that HEAD and OPTIONS methods are excluded from spec."""
        router = Router()

        @route("/users", methods=["GET", "HEAD", "OPTIONS"])
        def get_users(request: Request):
            return Response.for_json([])

        router.add(get_users)

        spec = generate_openapi_spec(router)

        assert "get" in spec["paths"]["/users"]
        assert "head" not in spec["paths"]["/users"]
        assert "options" not in spec["paths"]["/users"]

    def test_spec_includes_empty_websocket_path(self):
        """Test that WEBSOCKET methods are excluded from operation objects, but still create an empty path entry."""
        router = Router()

        @route("/socket", methods=["WEBSOCKET"])
        def my_websocket(request: Request):
            pass

        router.add(my_websocket)

        spec = generate_openapi_spec(router)

        assert "/socket" in spec["paths"]
        assert spec["paths"]["/socket"] == {}

    def test_spec_with_multiline_docstring_description(self):
        """Test that only the first paragraph of a docstring is used as description."""
        router = Router()

        @route("/users", methods=["GET"])
        def get_users(request: Request):
            """
            Get all users.

            This endpoint returns a list of all users in the system.
            This part should not be in the description.
            """
            return Response.for_json([])

        router.add(get_users)

        spec = generate_openapi_spec(router)
        path_spec = spec["paths"]["/users"]["get"]

        assert path_spec["description"] == "Get all users."

    def test_spec_with_default_response(self):
        """Test that default 200 response is added when none specified."""
        router = Router()

        @route("/users", methods=["GET"])
        def get_users(request: Request):
            return Response.for_json([])

        router.add(get_users)

        spec = generate_openapi_spec(router)
        path_spec = spec["paths"]["/users"]["get"]

        assert "responses" in path_spec
        assert "200" in path_spec["responses"]
        assert path_spec["responses"]["200"]["description"] == "Successful response"

    def test_router_method_generate_openapi_spec(self):
        """Test the Router.generate_openapi_spec convenience method."""
        router = Router()

        @route("/hello", methods=["GET"])
        def hello(request: Request):
            """Say hello"""
            return Response("Hello")

        router.add(hello)

        # Test using the Router method
        spec = router.generate_openapi_spec(info={"title": "Test API", "version": "1.0.0"})

        assert spec["openapi"] == "3.1.0"
        assert spec["info"]["title"] == "Test API"
        assert "/hello" in spec["paths"]

    def test_path_parameters_auto_generated(self):
        """Test that path parameters are automatically added to operations."""
        router = Router()

        @route("/users/<user_id>", methods=["GET"])
        def get_user(request: Request, user_id: str):
            return Response.for_json({"id": user_id})

        router.add(get_user)

        spec = generate_openapi_spec(router)
        path_spec = spec["paths"]["/users/{user_id}"]["get"]

        # Verify parameters are automatically added
        assert "parameters" in path_spec
        assert len(path_spec["parameters"]) == 1
        assert path_spec["parameters"][0]["name"] == "user_id"
        assert path_spec["parameters"][0]["in"] == "path"
        assert path_spec["parameters"][0]["required"] is True
        assert path_spec["parameters"][0]["schema"]["type"] == "string"

    def test_path_parameters_with_types(self):
        """Test that typed path parameters have correct OpenAPI types."""
        router = Router()

        @route("/items/<int:item_id>", methods=["DELETE"])
        def delete_item(request: Request, item_id: int):
            return Response("", status=204)

        router.add(delete_item)

        spec = generate_openapi_spec(router)
        path_spec = spec["paths"]["/items/{item_id}"]["delete"]

        # Verify integer type is correctly mapped
        assert "parameters" in path_spec
        assert path_spec["parameters"][0]["name"] == "item_id"
        assert path_spec["parameters"][0]["schema"]["type"] == "integer"

    def test_path_parameters_merged_with_existing(self):
        """Test that path parameters are merged with manually defined parameters."""
        router = Router()

        @route(
            "/posts/<post_id>/comments",
            methods=["GET"],
            openapi={
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}}
                ]
            },
        )
        def get_comments(request: Request, post_id: str):
            return Response.for_json([])

        router.add(get_comments)

        spec = generate_openapi_spec(router)
        path_spec = spec["paths"]["/posts/{post_id}/comments"]["get"]

        # Verify both path and query parameters are present
        assert "parameters" in path_spec
        assert len(path_spec["parameters"]) == 2

        param_names = {p["name"] for p in path_spec["parameters"]}
        assert "post_id" in param_names
        assert "limit" in param_names

        # Verify the path parameter was added correctly
        path_param = next(p for p in path_spec["parameters"] if p["name"] == "post_id")
        assert path_param["in"] == "path"
        assert path_param["required"] is True

        # Verify the query parameter is still there
        query_param = next(p for p in path_spec["parameters"] if p["name"] == "limit")
        assert query_param["in"] == "query"

    def test_spec_with_operation_id_with_method_prefix(self):
        """Test that operationId is prefixed with the method name."""
        router = Router()

        @route(
            "/my-resource",
            methods=["GET", "POST"],
            openapi={
                "operationId": "my_resource_op",
            },
        )
        def my_resource(request: Request):
            return Response("OK")

        router.add(my_resource)

        spec = generate_openapi_spec(router)

        assert spec["paths"]["/my-resource"]["get"]["operationId"] == "get_my_resource_op"
        assert spec["paths"]["/my-resource"]["post"]["operationId"] == "post_my_resource_op"


class TestTypedDictSchemaGeneration:
    """Tests for automatic schema generation from TypedDict return types."""

    def test_simple_typeddict_return_type(self):
        """Test that a simple TypedDict return type generates schema and response."""
        from typing import NotRequired, TypedDict

        class User(TypedDict):
            """A user object."""

            id: int
            name: str
            email: NotRequired[str]

        router = Router()

        @route("/users")
        def get_users(request: Request) -> list[User]:
            return []

        router.add(get_users)

        spec = generate_openapi_spec(router)

        # Check that schema was added to components
        assert "components" in spec
        assert "schemas" in spec["components"]
        assert "User" in spec["components"]["schemas"]

        user_schema = spec["components"]["schemas"]["User"]
        assert user_schema["type"] == "object"
        assert user_schema["description"] == "A user object."
        assert "properties" in user_schema
        assert "id" in user_schema["properties"]
        assert user_schema["properties"]["id"]["type"] == "integer"
        assert "name" in user_schema["properties"]
        assert user_schema["properties"]["name"]["type"] == "string"
        assert "email" in user_schema["properties"]
        assert user_schema["properties"]["email"]["type"] == "string"

        # Check required fields
        assert "required" in user_schema
        assert "id" in user_schema["required"]
        assert "name" in user_schema["required"]
        assert "email" not in user_schema["required"]

        # Check that response references the schema
        path_spec = spec["paths"]["/users"]["get"]
        assert "responses" in path_spec
        assert "200" in path_spec["responses"]
        response = path_spec["responses"]["200"]
        assert "content" in response
        assert "application/json" in response["content"]
        schema = response["content"]["application/json"]["schema"]
        assert schema["type"] == "array"
        assert schema["items"]["$ref"] == "#/components/schemas/User"

    def test_nested_typeddict(self):
        """Test that nested TypedDict types generate all schemas."""
        from typing import NotRequired, TypedDict

        class Address(TypedDict):
            """An address."""

            street: str
            city: str

        class Person(TypedDict):
            """A person with an address."""

            name: str
            address: NotRequired[Address]

        router = Router()

        @route("/person")
        def get_person(request: Request) -> Person:
            return {"name": "John"}

        router.add(get_person)

        spec = generate_openapi_spec(router)

        # Check that both schemas were added
        assert "components" in spec
        assert "schemas" in spec["components"]
        assert "Person" in spec["components"]["schemas"]
        assert "Address" in spec["components"]["schemas"]

        # Check nested reference
        person_schema = spec["components"]["schemas"]["Person"]
        assert "address" in person_schema["properties"]
        assert person_schema["properties"]["address"]["$ref"] == "#/components/schemas/Address"

        # Check response for single object (not array)
        path_spec = spec["paths"]["/person"]["get"]
        response = path_spec["responses"]["200"]
        schema = response["content"]["application/json"]["schema"]
        assert schema["$ref"] == "#/components/schemas/Person"

    def test_typeddict_with_openapi_metadata(self):
        """Test that TypedDict response works with manual openapi metadata."""
        from typing import TypedDict

        class Item(TypedDict):
            """An item."""

            id: int
            name: str

        router = Router()

        @route(
            "/items",
            openapi={
                "summary": "List items",
                "tags": ["items"],
            },
        )
        def get_items(request: Request) -> list[Item]:
            return []

        router.add(get_items)

        spec = generate_openapi_spec(router)

        # Check schema is generated
        assert "Item" in spec["components"]["schemas"]

        # Check manual metadata is preserved
        path_spec = spec["paths"]["/items"]["get"]
        assert path_spec["summary"] == "List items"
        assert path_spec["tags"] == ["items"]

        # Check auto-generated response
        response = path_spec["responses"]["200"]
        assert "content" in response
        schema = response["content"]["application/json"]["schema"]
        assert schema["type"] == "array"
        assert schema["items"]["$ref"] == "#/components/schemas/Item"

    def test_no_return_type_annotation(self):
        """Test that routes without return type annotation still work."""
        router = Router()

        @route("/test")
        def get_test(request: Request):
            return Response.for_json({"message": "test"})

        router.add(get_test)

        spec = generate_openapi_spec(router)

        # Should not have components section
        assert "components" not in spec or not spec["components"].get("schemas")

        # Should have default response
        path_spec = spec["paths"]["/test"]["get"]
        assert "responses" in path_spec
        assert "200" in path_spec["responses"]

    def test_non_typeddict_return_type(self):
        """Test that non-TypedDict return types don't generate schemas."""
        router = Router()

        @route("/string")
        def get_string(request: Request) -> str:
            return "hello"

        @route("/dict")
        def get_dict(request: Request) -> dict:
            return {}

        router.add(get_string)
        router.add(get_dict)

        spec = generate_openapi_spec(router)

        # Should not have components section for non-TypedDict types
        assert "components" not in spec or not spec["components"].get("schemas")

        # Should have default responses
        assert "responses" in spec["paths"]["/string"]["get"]
        assert "responses" in spec["paths"]["/dict"]["get"]


class TestOpenAPIFiltering:
    """Test the only_with_metadata filtering feature."""

    def test_only_with_metadata_includes_routes_with_openapi(self):
        """Routes with explicit OpenAPI metadata should be included when filtering."""
        from rolo import Router, route

        router = Router()

        @route("/_aws/lambda/runtimes", methods=["GET"], openapi={"summary": "List runtimes"})
        def list_runtimes(request):
            return {}

        router.add(list_runtimes)

        spec = router.generate_openapi_spec(only_with_metadata=True)

        assert "/_aws/lambda/runtimes" in spec["paths"]
        assert "get" in spec["paths"]["/_aws/lambda/runtimes"]

    def test_only_with_metadata_excludes_routes_without_openapi(self):
        """Routes without OpenAPI metadata should be excluded when filtering."""
        from rolo import Router, route

        router = Router()

        # Route without OpenAPI metadata
        @route("/health", methods=["GET"])
        def health(request):
            return {}

        router.add(health)

        spec = router.generate_openapi_spec(only_with_metadata=True)

        assert "/health" not in spec["paths"]

    def test_only_with_metadata_mixed_routes(self):
        """Test filtering with a mix of routes with and without metadata."""
        from rolo import Router, route

        router = Router()

        # Route with metadata
        @route("/_aws/lambda/runtimes", methods=["GET"], openapi={"summary": "List runtimes"})
        def list_runtimes(request):
            return {}

        # Route without metadata
        @route("/internal/status", methods=["GET"])
        def status(request):
            return {}

        router.add(list_runtimes)
        router.add(status)

        # Without filtering - both included
        spec_no_filter = router.generate_openapi_spec(only_with_metadata=False)
        assert "/_aws/lambda/runtimes" in spec_no_filter["paths"]
        assert "/internal/status" in spec_no_filter["paths"]

        # With filtering - only the one with metadata
        spec_with_filter = router.generate_openapi_spec(only_with_metadata=True)
        assert "/_aws/lambda/runtimes" in spec_with_filter["paths"]
        assert "/internal/status" not in spec_with_filter["paths"]


class TestRequestBodySchemaGeneration:
    """Test automatic request body schema generation from parameter type annotations."""

    def test_post_with_typeddict_parameter(self):
        """POST endpoint with TypedDict parameter should auto-generate requestBody."""
        from typing import TypedDict
        from rolo import Router, route

        class CreateUserRequest(TypedDict):
            """Request to create a user."""
            username: str
            email: str

        router = Router()

        @route("/users", methods=["POST"])
        def create_user(request, user: CreateUserRequest):
            return {"id": 123}

        router.add(create_user)

        spec = router.generate_openapi_spec()

        # Verify requestBody was auto-generated
        assert "requestBody" in spec["paths"]["/users"]["post"]
        request_body = spec["paths"]["/users"]["post"]["requestBody"]
        assert request_body["required"] is True
        assert "application/json" in request_body["content"]
        schema_ref = request_body["content"]["application/json"]["schema"]
        assert schema_ref == {"$ref": "#/components/schemas/CreateUserRequest"}

        # Verify schema was extracted
        assert "CreateUserRequest" in spec["components"]["schemas"]
        schema = spec["components"]["schemas"]["CreateUserRequest"]
        assert schema["type"] == "object"
        assert "username" in schema["properties"]
        assert "email" in schema["properties"]

    def test_get_without_request_body(self):
        """GET endpoint should not auto-generate requestBody."""
        from typing import TypedDict
        from rolo import Router, route

        class UserQuery(TypedDict):
            limit: int

        router = Router()

        @route("/users", methods=["GET"])
        def list_users(request, query: UserQuery):
            return []

        router.add(list_users)

        spec = router.generate_openapi_spec()

        # GET should not have requestBody even with TypedDict parameter
        assert "requestBody" not in spec["paths"]["/users"]["get"]

    def test_put_with_typeddict_parameter(self):
        """PUT endpoint with TypedDict parameter should auto-generate requestBody."""
        from typing import TypedDict
        from rolo import Router, route

        class UpdateUserRequest(TypedDict):
            email: str

        router = Router()

        @route("/users/<user_id>", methods=["PUT"])
        def update_user(request, user_id: str, user: UpdateUserRequest):
            return {"id": user_id}

        router.add(update_user)

        spec = router.generate_openapi_spec()

        # Verify requestBody was auto-generated for PUT
        assert "requestBody" in spec["paths"]["/users/{user_id}"]["put"]

    def test_manual_request_body_not_overridden(self):
        """Manual requestBody in openapi metadata should not be overridden."""
        from typing import TypedDict
        from rolo import Router, route

        class CreateItemRequest(TypedDict):
            name: str

        router = Router()

        @route(
            "/items",
            methods=["POST"],
            openapi={
                "requestBody": {
                    "required": False,
                    "content": {"application/xml": {"schema": {"type": "string"}}},
                }
            },
        )
        def create_item(request, item: CreateItemRequest):
            return {"id": 1}

        router.add(create_item)

        spec = router.generate_openapi_spec()

        # Manual requestBody should be preserved
        request_body = spec["paths"]["/items"]["post"]["requestBody"]
        assert request_body["required"] is False
        assert "application/xml" in request_body["content"]

    def test_request_body_type_from_metadata(self):
        """requestBodyType in metadata should auto-generate requestBody."""
        from typing import TypedDict
        from rolo import Router, route

        class LoginRequest(TypedDict):
            """Login request body."""
            username: str
            password: str

        router = Router()

        @route(
            "/login",
            methods=["POST"],
            openapi={
                "summary": "User login",
                "requestBodyType": LoginRequest,  # Reference the TypedDict class directly
            },
        )
        def login(request):
            return {"token": "abc123"}

        router.add(login)

        spec = router.generate_openapi_spec()

        # Verify requestBody was auto-generated from metadata
        assert "requestBody" in spec["paths"]["/login"]["post"]
        request_body = spec["paths"]["/login"]["post"]["requestBody"]
        assert request_body["required"] is True
        schema_ref = request_body["content"]["application/json"]["schema"]
        assert schema_ref == {"$ref": "#/components/schemas/LoginRequest"}

        # Verify requestBodyType was removed from operation metadata
        assert "requestBodyType" not in spec["paths"]["/login"]["post"]

        # Verify schema was extracted
        assert "LoginRequest" in spec["components"]["schemas"]
        schema = spec["components"]["schemas"]["LoginRequest"]
        assert "username" in schema["properties"]
        assert "password" in schema["properties"]


class TestResourceDecoratorWithMethodSpecificMetadata:
    """Tests for @resource decorator with method-specific OpenAPI metadata."""

    def test_resource_decorator_with_method_specific_metadata(self):
        """Resource decorator with openapi={"get": {...}, "post": {...}} should generate correct spec."""
        from rolo.resource import resource
        from rolo import Router

        @resource(
            "/health",
            openapi={
                "get": {
                    "summary": "Get health status",
                    "description": "Returns the health status",
                    "tags": ["info"],
                },
                "post": {
                    "summary": "Control instance",
                    "description": "Restart or kill the instance",
                    "tags": ["internal"],
                },
            },
        )
        class HealthResource:
            def on_get(self, request):
                return {"status": "ok"}

            def on_post(self, request):
                return {"status": "ok"}

        router = Router()
        router.add(HealthResource())

        spec = router.generate_openapi_spec(only_with_metadata=True)

        # Verify both methods are present
        assert "/health" in spec["paths"]
        assert "get" in spec["paths"]["/health"]
        assert "post" in spec["paths"]["/health"]

        # Verify GET has correct metadata
        get_op = spec["paths"]["/health"]["get"]
        assert get_op["summary"] == "Get health status"
        assert get_op["description"] == "Returns the health status"
        assert get_op["tags"] == ["info"]

        # Verify POST has correct metadata
        post_op = spec["paths"]["/health"]["post"]
        assert post_op["summary"] == "Control instance"
        assert post_op["description"] == "Restart or kill the instance"
        assert post_op["tags"] == ["internal"]

        # Verify no method bleeding (GET shouldn't have POST metadata and vice versa)
        assert get_op["summary"] != post_op["summary"]
        assert get_op["tags"] != post_op["tags"]
