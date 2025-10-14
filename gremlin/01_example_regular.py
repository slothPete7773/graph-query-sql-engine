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


def demo_hybrid_approach():
    """
    Demonstrate hybrid AST + Visitor pattern
    Query: Find call events for subscriber 12345 with duration > 60 seconds
    Gremlin: g.V().has('subscriber', 'a_subscriber_id', eq(12345))
              .out('calls')
              .has('call_event', 'duration_seconds', gt(60))
    """

    # Get the CDR graph schema
    graph_schema = get_cdr_graph_schema()

    print("=" * 80)
    print("HYBRID APPROACH: Simple AST + Visitor Pattern")
    print("=" * 80)

    # STEP 1: Build AST using simple chained approach
    print("\n[STEP 1] Building AST from Gremlin-like API...")
    print("Query: Find call events for subscriber 12345 with duration > 60 seconds")
    builder = GremlinASTBuilder()
    ast = (
        builder.V()
        .has("subscriber", "a_subscriber_id", Predicate(PredicateOp.EQ, 12345))
        .out("calls")
        .has("call_event", "duration_seconds", Predicate(PredicateOp.GT, 60))
        .build()
    )

    # Print AST structure
    print("\nAST Structure:")
    current = ast
    step_num = 1
    while current:
        print(f"  Step {step_num}: {current.step_type}({current.args})")
        current = current.next_step
        step_num += 1

    # # STEP 2: Analyze query using Analyzer Visitor
    # print("\n[STEP 2] Analyzing query for optimization...")
    # analyzer = QueryAnalyzerVisitor()
    # analyzer.visit(ast)
    # analysis = analyzer.get_analysis()

    # print("\nQuery Analysis:")
    # for key, value in analysis.items():
    #     print(f"  {key}: {value}")

    # STEP 3: Generate SQL using SQL Generator Visitor
    sql_generator = SQLGeneratorVisitor(graph_schema)
    sql_generator.visit(ast)
    sql = sql_generator.generate_sql()

    print("\nGenerated SQL:")
    print("-" * 80)
    print(sql)
    print("-" * 80)


if __name__ == "__main__":
    demo_hybrid_approach()
