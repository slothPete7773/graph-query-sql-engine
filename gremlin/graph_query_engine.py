"""
Hybrid Approach: Simple Node-Based AST + Visitor Pattern
Converts Gremlin queries to optimized SQL with filter push-down

This module provides the main interface for the graph query engine.
The implementation is split across multiple modules:
- ast_nodes.py: AST node definitions and builder
- visitors.py: Visitor pattern implementations for SQL generation and analysis
- schema.py: Graph schema definitions
- demo.py: Example usage and demonstrations
"""

# Try relative imports first (when imported as a module)
try:
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
except ImportError:
    # Fall back to absolute imports (when run directly)
    from ast_nodes import (
        ASTNode,
        GremlinASTBuilder,
        Predicate,
        PredicateOp,
    )
    from visitors import (
        GremlinVisitor,
        SQLGeneratorVisitor,
        QueryAnalyzerVisitor,
    )
    from schema import get_cdr_graph_schema

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


if __name__ == "__main__":
    # Run the demo when executed directly
    try:
        from .demo import demo_hybrid_approach
    except ImportError:
        from demo import demo_hybrid_approach

    demo_hybrid_approach()
