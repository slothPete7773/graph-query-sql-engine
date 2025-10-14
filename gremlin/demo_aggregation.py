"""
Demo script showing complex Gremlin query with aggregation, grouping, and ordering

This demonstrates converting a complex SQL query with GROUP BY, aggregations,
ORDER BY, and LIMIT to a Gremlin traversal.

SQL Query:
SELECT
    a.a_number AS caller,
    a.b_number AS callee,
    COUNT(*) AS call_count,
    SUM(a.duration_seconds) AS total_duration
FROM redberry.fact_cdr AS a
WHERE a.event_type = 'VOICE'
    AND a.operator = 'CAT'
GROUP BY a.a_number, a.b_number
ORDER BY call_count DESC
LIMIT 20
"""

# Try relative imports first (when imported as a module)
try:
    from .ast_nodes import GremlinASTBuilder, Predicate, PredicateOp
    from .visitors import SQLGeneratorVisitor
    from .schema import get_cdr_graph_schema
except ImportError:
    # Fall back to absolute imports (when run directly)
    from ast_nodes import GremlinASTBuilder, Predicate, PredicateOp
    from visitors import SQLGeneratorVisitor
    from schema import get_cdr_graph_schema


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

    print("=" * 80)
    print("COMPLEX AGGREGATION QUERY DEMO")
    print("=" * 80)

    print("\n[TARGET SQL]")
    print("-" * 80)
    sql = """SELECT
    a.a_number AS caller,
    a.b_number AS callee,
    COUNT(*) AS call_count,
    SUM(a.duration_seconds) AS total_duration
FROM redberry.fact_cdr AS a
WHERE a.event_type = 'VOICE'
    AND a.operator = 'CAT'
GROUP BY a.a_number, a.b_number
ORDER BY call_count DESC
LIMIT 20"""
    print(sql)
    print("-" * 80)

    print("\n[GREMLIN TRAVERSAL BUILD]")
    print("-" * 80)

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

    print("\n[COMPARISON]")
    print("-" * 80)
    print("Expected SQL:")
    print(sql)
    print()
    print("Generated SQL:")
    print(generated_sql)
    print("-" * 80)

    print("\n[NOTES]")
    print("-" * 80)
    print("""
The SQL generator now supports:
✓ Filtering with has() steps (WHERE clause)
✓ Grouping with group().by() steps (GROUP BY clause)
✓ COUNT(*) aggregation with count() step
✓ SUM(field) aggregation with sum(field) step
✓ Ordering with order().by() steps (ORDER BY clause)
✓ Limiting results with limit() step (LIMIT clause)

The generated SQL may differ slightly in formatting but should be
functionally equivalent to the target SQL.
""")
    print("-" * 80)


if __name__ == "__main__":
    demo_complex_aggregation_query()
