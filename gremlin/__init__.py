"""
Gremlin to SQL Query Engine

A hybrid AST + Visitor pattern implementation for converting Gremlin graph
traversal queries to optimized SQL queries with filter push-down.
"""

from .ast_nodes import (
    ASTNode,
    GremlinASTBuilder,
    Predicate,
    PredicateOp,
)
from .visitors import (
    GremlinVisitor,
    SQLGeneratorVisitor,
    QueryAnalyzerVisitor,
)
from .schema import get_cdr_graph_schema

__version__ = "0.1.0"

__all__ = [
    "ASTNode",
    "GremlinASTBuilder",
    "Predicate",
    "PredicateOp",
    "GremlinVisitor",
    "SQLGeneratorVisitor",
    "QueryAnalyzerVisitor",
    "get_cdr_graph_schema",
]
