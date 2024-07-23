"""
DEPRECATED: use ``from rolo.routing import handler_dispatcher`` instead
"""
from .routing.handler import ResultValue, handler_dispatcher

__all__ = [
    "handler_dispatcher",
    "ResultValue",
]
