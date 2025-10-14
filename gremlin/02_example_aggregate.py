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


def demo_complex_aggregation_query():
    """
    Demonstrate complex aggregation query in Gremlin style

    Gremlin conceptual traversal:
    g.V().hasLabel('call_event')
     .has('event_type', 'VOICE')
     .has('operator', 'CAT')
     .group()
       .by(values('a_number', 'b_number'))  // GROUP BY
       .by(fold().coalesce(
         project('call_count', 'total_duration')
           .by(count())
           .by(sum('duration_seconds'))
       ))
     .order().by(select('call_count'), desc)
     .limit(20)
    """

    # Get schema
    graph_schema = get_cdr_graph_schema()

    # Build the Gremlin-style AST
    builder = GremlinASTBuilder()
    ast = (
        builder.V()
        .has("call_event", "event_type", Predicate(PredicateOp.EQ, "VOICE"))
        .has("call_event", "operator", Predicate(PredicateOp.EQ, "CAT"))
        .group()
        .by("a_number", "b_number")  # Group by these fields
        .count()  # COUNT(*)
        .sum("duration_seconds")  # SUM(duration_seconds)
        .order()
        .by("call_count", "desc")  # Order by call_count descending
        .limit(20)
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

    print("\n[SQL GENERATION]")
    print("-" * 80)

    # Generate SQL using the visitor
    sql_generator = SQLGeneratorVisitor(graph_schema)
    sql_generator.visit(ast)
    generated_sql = sql_generator.generate_sql()

    print("Generated SQL:")
    print(generated_sql)
    print("-" * 80)

    # print("\n[COMPARISON]")
    # print("-" * 80)
    # print("Expected SQL:")
    # print(sql)
    # print()
    # print("Generated SQL:")
    # print(generated_sql)
    # print("-" * 80)


if __name__ == "__main__":
    demo_complex_aggregation_query()
