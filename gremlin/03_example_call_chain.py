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


def demo_call_chain_traversal():
    """
    Demonstrate SQL generation for call chain traversal
    This shows how the repeat/times pattern translates to recursive CTEs

    Gremlin conceptual traversal:
    g.V().hasLabel('subscriber')
     .has('a_number', '0812345678')
     .repeat(
       out('calls')
       .has('event_type', 'VOICE')
       .has('operator', 'CAT')
     )
     .times(3)
     .emit()
     .path()
     .limit(50)

    This will traverse up to 3 hops in the call chain, finding subscribers
    who called other subscribers with VOICE calls on the CAT operator network.
    """

    # Get schema
    graph_schema = get_cdr_graph_schema()

    # Create the Gremlin-style AST using the builder pattern
    g = GremlinASTBuilder()

    # Create repeat traversal pattern
    repeat_traversal = GremlinASTBuilder()
    repeat_traversal.out("calls").has(
        "event_type", Predicate(PredicateOp.EQ, "VOICE")
    ).has("operator", Predicate(PredicateOp.EQ, "CAT"))

    # Build main traversal
    ast = (
        g.V()
        .hasLabel("subscriber")
        .has("a_number", Predicate(PredicateOp.EQ, "0812345678"))
        .repeat(repeat_traversal.build())
        .times(3)
        .emit()
        .path()
        .limit(50)
        .build()
    )

    # Print AST structure
    print("Gremlin AST Steps:")
    current = ast
    step_num = 1
    while current:
        args_str = ", ".join(str(arg) for arg in current.args)
        print(f"  {step_num}. {current.step_type}({args_str})")
        current = current.next_step
        step_num += 1

    print("-" * 80)

    # print("\n[SQL GENERATION]")
    # print("-" * 80)

    # Generate SQL using the visitor
    sql_generator = SQLGeneratorVisitor(graph_schema)
    sql_generator.visit(ast)
    generated_sql = sql_generator.generate_sql()

    print("Generated SQL:")
    print(generated_sql)
    print("-" * 80)


if __name__ == "__main__":
    demo_call_chain_traversal()
