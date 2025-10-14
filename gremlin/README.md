# Gremlin to SQL Query Engine

A hybrid AST + Visitor pattern implementation for converting Gremlin graph traversal queries to optimized SQL queries with filter push-down.

## Architecture

The codebase is organized into separate modules for clarity and maintainability:

### Core Modules

- **`ast_nodes.py`**: AST (Abstract Syntax Tree) node definitions
  - `ASTNode`: Linked-list node representing a Gremlin step
  - `GremlinASTBuilder`: Fluent API for building AST from Gremlin-like queries
  - `Predicate` & `PredicateOp`: Predicate operators for filtering

- **`visitors.py`**: Visitor pattern implementations
  - `GremlinVisitor`: Abstract base visitor
  - `SQLGeneratorVisitor`: Generates optimized SQL with filter push-down
  - `QueryAnalyzerVisitor`: Analyzes queries for optimization opportunities

- **`schema.py`**: Graph schema definitions
  - `get_cdr_graph_schema()`: Returns CDR (Call Detail Record) graph schema

- **`demo.py`**: Demonstration and example usage
  - `demo_hybrid_approach()`: Shows end-to-end Gremlin to SQL conversion

- **`graph_query_engine.py`**: Main entry point
  - Re-exports all public APIs
  - Can be run directly to execute demo

## Key Features

### 1. Simple AST Construction
```python
from ast_nodes import GremlinASTBuilder, Predicate, PredicateOp

builder = GremlinASTBuilder()
ast = (
    builder.V()
    .has("subscriber", "a_subscriber_id", Predicate(PredicateOp.EQ, 12345))
    .out("calls")
    .has("call_event", "duration_seconds", Predicate(PredicateOp.GT, 60))
    .build()
)
```

### 2. SQL Generation with Smart Join Optimization
The `SQLGeneratorVisitor` automatically detects when all tables are the same and avoids unnecessary self-joins:

**Before (with self-joins):**
```sql
SELECT *
FROM redberry.redberry.fact_cdr AS v0
INNER JOIN redberry.redberry.fact_cdr AS e1 ON v0.a_subscriber_id = e1.a_subscriber_id
INNER JOIN redberry.redberry.fact_cdr AS v2 ON e1.event_id = v2.event_id
WHERE v0.a_subscriber_id = 12345 AND v2.duration_seconds > 60
```

**After (optimized):**
```sql
SELECT *
FROM redberry.redberry.fact_cdr AS v0
WHERE v0.a_subscriber_id = 12345 AND v0.duration_seconds > 60
```

### 3. Query Analysis
```python
from visitors import QueryAnalyzerVisitor

analyzer = QueryAnalyzerVisitor()
analyzer.visit(ast)
analysis = analyzer.get_analysis()
# Returns: num_filters, num_traversals, estimated_selectivity, recommendation
```

## Usage

### Running the Demos

**Basic Demo** (Simple traversal with filters):
```bash
cd gremlin
python demo.py
```

or

```bash
python graph_query_engine.py
```

**Aggregation Demo** (Complex query with GROUP BY, aggregations, ORDER BY, LIMIT):
```bash
cd gremlin
python demo_aggregation.py
```

This demonstrates the conceptual mapping for a complex SQL query:
```sql
SELECT
    a.a_number AS caller,
    a.b_number AS callee,
    COUNT(*) AS call_count,
    SUM(a.duration_seconds) AS total_duration
FROM redberry.fact_cdr AS a
WHERE a.event_type = 'VOICE' AND a.operator = 'CAT'
GROUP BY a.a_number, a.b_number
ORDER BY call_count DESC
LIMIT 20
```

### Using in Your Code
```python
from gremlin import (
    GremlinASTBuilder,
    Predicate,
    PredicateOp,
    SQLGeneratorVisitor,
    get_cdr_graph_schema
)

# Build AST
builder = GremlinASTBuilder()
ast = builder.V().has("subscriber", "a_subscriber_id",
                       Predicate(PredicateOp.EQ, 12345)).build()

# Generate SQL
schema = get_cdr_graph_schema()
sql_generator = SQLGeneratorVisitor(schema)
sql_generator.visit(ast)
sql = sql_generator.generate_sql()
print(sql)
```

## Schema Structure

The schema follows this structure:
```python
{
    "vertices": [
        {
            "label": "subscriber",
            "oneToOne": {
                "tableSource": {"catalog": "...", "schema": "...", "table": "..."},
                "id": {"fields": [{"type": "...", "field": "...", "alias": "..."}]},
                "attributes": [...]
            }
        }
    ],
    "edges": [
        {
            "label": "calls",
            "fromVertex": "subscriber",
            "toVertex": "call_event",
            "tableSource": {...},
            "fromId": {"fields": [...]},
            "toId": {"fields": [...]}
        }
    ]
}
```

## Design Patterns

1. **Builder Pattern**: `GremlinASTBuilder` provides a fluent API
2. **Visitor Pattern**: Separates traversal logic from processing logic
3. **Strategy Pattern**: Different visitors can process the same AST differently

## Future Enhancements

- Support for aggregation functions (count, sum, avg)
- Support for grouping and ordering
- Support for multiple schemas
- Query optimization based on statistics
- Support for more complex traversal patterns
