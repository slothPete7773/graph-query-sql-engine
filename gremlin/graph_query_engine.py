"""
Hybrid Approach: Simple Node-Based AST + Visitor Pattern
Converts Gremlin queries to optimized SQL with filter push-down

Example: g.V().has('User', 'age', gt(25)).out('purchased').has('Product', 'price', lt(100))
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict
from abc import ABC, abstractmethod
from enum import Enum


# ============================================================================
# PART 1: Simple Node-Based AST (Easy to Build)
# ============================================================================


class PredicateOp(Enum):
    GT = "gt"
    LT = "lt"
    EQ = "eq"
    GTE = "gte"
    LTE = "lte"
    NEQ = "neq"


@dataclass
class Predicate:
    """Represents a comparison predicate"""

    operator: PredicateOp
    value: Any

    def to_sql_operator(self) -> str:
        mapping = {
            PredicateOp.GT: ">",
            PredicateOp.LT: "<",
            PredicateOp.EQ: "=",
            PredicateOp.GTE: ">=",
            PredicateOp.LTE: "<=",
            PredicateOp.NEQ: "!=",
        }
        return mapping[self.operator]


@dataclass
class ASTNode:
    """Simple linked-list node representing one Gremlin step"""

    step_type: str  # 'V', 'has', 'out', 'in', etc.
    args: List[Any] = field(default_factory=list)
    next_step: Optional["ASTNode"] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def accept(self, visitor: "GremlinVisitor"):
        """Accept visitor for processing"""
        return visitor.visit(self)


class GremlinASTBuilder:
    """Builder for constructing AST from Gremlin-like API"""

    def __init__(self):
        self.root: Optional[ASTNode] = None
        self.current: Optional[ASTNode] = None

    def V(self, *ids):
        """Start traversal at vertices"""
        return self._add_step("V", list(ids))

    def has(self, *args):
        """Filter step"""
        return self._add_step("has", list(args))

    def out(self, edge_label: str):
        """Traverse outgoing edges"""
        return self._add_step("out", [edge_label])

    def in_(self, edge_label: str):
        """Traverse incoming edges"""
        return self._add_step("in", [edge_label])

    def values(self, *property_keys):
        """Get property values"""
        return self._add_step("values", list(property_keys))

    def _add_step(self, step_type: str, args: List[Any]):
        """Internal method to add step to chain"""
        node = ASTNode(step_type=step_type, args=args)

        if self.root is None:
            self.root = node
        else:
            self.current.next_step = node

        self.current = node
        return self

    def build(self) -> ASTNode:
        """Return the root AST node"""
        return self.root


# ============================================================================
# PART 2: Visitor Pattern (For SQL Generation and Optimization)
# ============================================================================


class GremlinVisitor(ABC):
    """Abstract visitor for processing AST nodes"""

    @abstractmethod
    def visit(self, node: ASTNode):
        pass


class SQLGeneratorVisitor(GremlinVisitor):
    """
    Visitor that generates optimized SQL with filter push-down
    """

    def __init__(self, graph_schema: Dict[str, Any]):
        self.graph_schema = graph_schema
        self.tables: List[str] = []
        self.joins: List[str] = []
        self.where_clauses: List[str] = []
        self.select_columns: List[str] = ["*"]
        self.table_counter = 0
        self.current_table_alias = None
        self.current_vertex_id_field = None  # Track current vertex ID field
        self.current_table_name = None  # Track current table name

    def visit(self, node: ASTNode):
        """Main visit method that dispatches to specific handlers"""
        if node is None:
            return

        # Dispatch based on step type
        method_name = f"visit_{node.step_type}"
        if hasattr(self, method_name):
            getattr(self, method_name)(node)
        else:
            raise NotImplementedError(f"Step '{node.step_type}' not implemented")

        # Continue to next step
        if node.next_step:
            self.visit(node.next_step)

    def visit_V(self, node: ASTNode):
        """Handle V() - start at vertices"""
        label = self._get_vertex_label_from_context(node)
        vertex_config = self._get_vertex_config(label)

        if vertex_config:
            table_source = vertex_config["oneToOne"]["tableSource"]
            table_name = f"{table_source['catalog']}.{table_source['schema']}.{table_source['table']}"
            id_field = vertex_config["oneToOne"]["id"]["fields"][0]["field"]
        else:
            # Fallback to default
            table_name = "vertices"
            id_field = "id"

        alias = f"v{self.table_counter}"
        self.table_counter += 1

        self.tables.append(f"{table_name} AS {alias}")
        self.current_table_alias = alias
        self.current_vertex_id_field = id_field  # Track the ID field
        self.current_table_name = table_name  # Track the table name

        # If specific IDs provided
        if node.args and node.args[0]:
            ids = node.args[0] if isinstance(node.args[0], list) else [node.args[0]]
            id_list = ", ".join(f"'{id}'" for id in ids)
            self.where_clauses.append(f"{alias}.{id_field} IN ({id_list})")

    def visit_has(self, node: ASTNode):
        """Handle has() - filter vertices/edges by property"""
        args = node.args

        if len(args) == 3:
            # has(label, key, predicate)
            label, key, predicate = args

            # This is a vertex label filter - handled in V() step
            if isinstance(predicate, Predicate):
                # Property filter with predicate
                sql_op = predicate.to_sql_operator()
                value = self._format_sql_value(predicate.value)
                self.where_clauses.append(
                    f"{self.current_table_alias}.{key} {sql_op} {value}"
                )

        elif len(args) == 2:
            # has(key, value) or has(key, predicate)
            key, value_or_predicate = args

            if isinstance(value_or_predicate, Predicate):
                sql_op = value_or_predicate.to_sql_operator()
                value = self._format_sql_value(value_or_predicate.value)
            else:
                sql_op = "="
                value = self._format_sql_value(value_or_predicate)

            self.where_clauses.append(
                f"{self.current_table_alias}.{key} {sql_op} {value}"
            )

    def visit_out(self, node: ASTNode):
        """Handle out() - traverse outgoing edges"""
        edge_label = node.args[0]

        # Get edge configuration from new schema
        edge_config = self._get_edge_config(edge_label)

        if edge_config:
            # Extract edge table information
            edge_table_source = edge_config["tableSource"]
            edge_table = f"{edge_table_source['catalog']}.{edge_table_source['schema']}.{edge_table_source['table']}"
            from_id_field = edge_config["fromId"]["fields"][0]["field"]
            to_id_field = edge_config["toId"]["fields"][0]["field"]

            # Get target vertex configuration
            target_vertex_label = edge_config["toVertex"]
            target_vertex_config = self._get_vertex_config(target_vertex_label)

            if target_vertex_config:
                target_table_source = target_vertex_config["oneToOne"]["tableSource"]
                target_table = f"{target_table_source['catalog']}.{target_table_source['schema']}.{target_table_source['table']}"
                target_id_field = target_vertex_config["oneToOne"]["id"]["fields"][0][
                    "field"
                ]
            else:
                target_table = "vertices"
                target_id_field = "id"
        else:
            # Fallback to defaults
            edge_table = "edges"
            from_id_field = "from_id"
            to_id_field = "to_id"
            target_table = "vertices"
            target_id_field = "id"

        # Check if all tables are the same (source, edge, target)
        # If so, avoid self-joins and just continue using the same alias
        if self.current_table_name == edge_table == target_table:
            # Same table - no join needed, just continue with same alias
            # The traversal is just filtering on the same table
            self.current_vertex_id_field = target_id_field
            # Don't update current_table_alias - keep using the same one
        else:
            # Different tables - need actual joins
            edge_alias = f"e{self.table_counter}"
            self.table_counter += 1
            vertex_alias = f"v{self.table_counter}"
            self.table_counter += 1

            # Join edge table - use current vertex ID field instead of hardcoded "id"
            source_id_field = self.current_vertex_id_field or "id"
            self.joins.append(
                f"INNER JOIN {edge_table} AS {edge_alias} "
                f"ON {self.current_table_alias}.{source_id_field} = {edge_alias}.{from_id_field}"
            )

            # Join target vertex table
            self.joins.append(
                f"INNER JOIN {target_table} AS {vertex_alias} "
                f"ON {edge_alias}.{to_id_field} = {vertex_alias}.{target_id_field}"
            )

            self.current_table_alias = vertex_alias
            self.current_vertex_id_field = target_id_field
            self.current_table_name = target_table

    def visit_in(self, node: ASTNode):
        """Handle in() - traverse incoming edges"""
        edge_label = node.args[0]

        # Get edge configuration from new schema
        edge_config = self._get_edge_config(edge_label)

        if edge_config:
            # Extract edge table information
            edge_table_source = edge_config["tableSource"]
            edge_table = f"{edge_table_source['catalog']}.{edge_table_source['schema']}.{edge_table_source['table']}"
            from_id_field = edge_config["fromId"]["fields"][0]["field"]
            to_id_field = edge_config["toId"]["fields"][0]["field"]

            # Get source vertex configuration
            source_vertex_label = edge_config["fromVertex"]
            source_vertex_config = self._get_vertex_config(source_vertex_label)

            if source_vertex_config:
                source_table_source = source_vertex_config["oneToOne"]["tableSource"]
                source_table = f"{source_table_source['catalog']}.{source_table_source['schema']}.{source_table_source['table']}"
                source_id_field = source_vertex_config["oneToOne"]["id"]["fields"][0][
                    "field"
                ]
            else:
                source_table = "vertices"
                source_id_field = "id"
        else:
            # Fallback to defaults
            edge_table = "edges"
            from_id_field = "from_id"
            to_id_field = "to_id"
            source_table = "vertices"
            source_id_field = "id"

        # Check if all tables are the same (current, edge, source)
        # If so, avoid self-joins and just continue using the same alias
        if self.current_table_name == edge_table == source_table:
            # Same table - no join needed, just continue with same alias
            # The traversal is just filtering on the same table
            self.current_vertex_id_field = source_id_field
            # Don't update current_table_alias - keep using the same one
        else:
            # Different tables - need actual joins
            edge_alias = f"e{self.table_counter}"
            self.table_counter += 1
            vertex_alias = f"v{self.table_counter}"
            self.table_counter += 1

            # Join edge table - use current vertex ID field instead of hardcoded "id"
            current_id_field = self.current_vertex_id_field or "id"
            self.joins.append(
                f"INNER JOIN {edge_table} AS {edge_alias} "
                f"ON {self.current_table_alias}.{current_id_field} = {edge_alias}.{to_id_field}"
            )

            self.joins.append(
                f"INNER JOIN {source_table} AS {vertex_alias} "
                f"ON {edge_alias}.{from_id_field} = {vertex_alias}.{source_id_field}"
            )

            self.current_table_alias = vertex_alias
            self.current_vertex_id_field = source_id_field
            self.current_table_name = source_table

    def visit_values(self, node: ASTNode):
        """Handle values() - select specific properties"""
        property_keys = node.args
        self.select_columns = [
            f"{self.current_table_alias}.{key}" for key in property_keys
        ]

    def _get_vertex_label_from_context(self, node: ASTNode) -> str:
        """Look ahead to find vertex label from has() step"""
        current = node.next_step
        while current:
            if current.step_type == "has" and len(current.args) == 3:
                return current.args[0]  # Label is first arg
            current = current.next_step
        return "default"

    def _get_vertex_config(self, label: str) -> Optional[Dict[str, Any]]:
        """Get vertex configuration from schema by label"""
        if "vertices" in self.graph_schema:
            for vertex in self.graph_schema["vertices"]:
                if vertex["label"] == label:
                    return vertex
        return None

    def _get_edge_config(self, label: str) -> Optional[Dict[str, Any]]:
        """Get edge configuration from schema by label"""
        if "edges" in self.graph_schema:
            for edge in self.graph_schema["edges"]:
                if edge["label"] == label:
                    return edge
        return None

    def _format_sql_value(self, value: Any) -> str:
        """Format Python value for SQL"""
        if isinstance(value, str):
            return f"'{value}'"
        return str(value)

    def generate_sql(self) -> str:
        """Generate final SQL query"""
        select_clause = f"SELECT {', '.join(self.select_columns)}"
        from_clause = f"FROM {self.tables[0]}"

        sql_parts = [select_clause, from_clause]

        if self.joins:
            sql_parts.extend(self.joins)

        if self.where_clauses:
            where_clause = f"WHERE {' AND '.join(self.where_clauses)}"
            sql_parts.append(where_clause)

        return "\n".join(sql_parts)


class QueryAnalyzerVisitor(GremlinVisitor):
    """
    Visitor that analyzes query before SQL generation
    Useful for optimization decisions
    """

    def __init__(self):
        self.vertex_filters = []
        self.edge_traversals = []
        self.has_aggregation = False
        self.estimated_selectivity = 1.0

    def visit(self, node: ASTNode):
        """Analyze each step"""
        if node is None:
            return

        if node.step_type == "has":
            self.vertex_filters.append(node.args)
            # Predicates typically reduce data by ~90%
            if len(node.args) == 3 and isinstance(node.args[2], Predicate):
                self.estimated_selectivity *= 0.1

        elif node.step_type in ["out", "in"]:
            self.edge_traversals.append(node.args[0])

        if node.next_step:
            self.visit(node.next_step)

    def get_analysis(self) -> Dict[str, Any]:
        """Return analysis results"""
        return {
            "num_filters": len(self.vertex_filters),
            "num_traversals": len(self.edge_traversals),
            "estimated_selectivity": self.estimated_selectivity,
            "recommendation": self._get_recommendation(),
        }

    def _get_recommendation(self) -> str:
        """Provide optimization recommendations"""

        if self.estimated_selectivity < 0.01:
            return "Highly selective query - good for SQL push-down"
        elif self.estimated_selectivity < 0.5:
            return "Moderately selective - SQL push-down recommended"
        else:
            return "Low selectivity - consider adding more filters"


# ============================================================================
# DEMONSTRATION
# ============================================================================


def demo_hybrid_approach():
    """
    Demonstrate hybrid AST + Visitor pattern
    Query: g.V().has('subscriber', 'a_subscriber_id', eq(12345)).out('calls').has('call_event', 'duration_seconds', gt(60))
    """

    # Define graph schema (based on redberry.fact_cdr table)
    graph_schema = {
        "vertices": [
            {
                "label": "subscriber",
                "oneToOne": {
                    "tableSource": {
                        "catalog": "redberry",
                        "schema": "redberry",
                        "table": "fact_cdr",
                    },
                    "id": {
                        "fields": [
                            {
                                "type": "UInt64",
                                "field": "a_subscriber_id",
                                "alias": "puppy_id_a_subscriber_id",
                            }
                        ]
                    },
                    "attributes": [
                        {
                            "type": "UInt64",
                            "field": "a_subscriber_id",
                            "alias": "a_subscriber_id",
                        },
                        {"type": "String", "field": "a_number", "alias": "a_number"},
                        {"type": "String", "field": "operator", "alias": "operator"},
                    ],
                },
            },
            {
                "label": "call_event",
                "oneToOne": {
                    "tableSource": {
                        "catalog": "redberry",
                        "schema": "redberry",
                        "table": "fact_cdr",
                    },
                    "id": {
                        "fields": [
                            {
                                "type": "UInt64",
                                "field": "event_id",
                                "alias": "puppy_id_event_id",
                            }
                        ]
                    },
                    "attributes": [
                        {"type": "UInt64", "field": "event_id", "alias": "event_id"},
                        {
                            "type": "String",
                            "field": "event_type",
                            "alias": "event_type",
                        },
                        {
                            "type": "DateTime",
                            "field": "event_datetime",
                            "alias": "event_datetime",
                        },
                        {
                            "type": "Int32",
                            "field": "duration_seconds",
                            "alias": "duration_seconds",
                        },
                        {"type": "String", "field": "b_number", "alias": "b_number"},
                        {"type": "Float64", "field": "latitude", "alias": "latitude"},
                        {"type": "Float64", "field": "longitude", "alias": "longitude"},
                    ],
                },
            },
        ],
        "edges": [
            {
                "label": "calls",
                "fromVertex": "subscriber",
                "toVertex": "call_event",
                "tableSource": {
                    "catalog": "redberry",
                    "schema": "redberry",
                    "table": "fact_cdr",
                },
                "id": {
                    "fields": [
                        {
                            "type": "UInt64",
                            "field": "event_id",
                            "alias": "puppy_id_event_id",
                        }
                    ]
                },
                "fromId": {
                    "fields": [
                        {
                            "type": "UInt64",
                            "field": "a_subscriber_id",
                            "alias": "puppy_from_a_subscriber_id",
                        }
                    ]
                },
                "toId": {
                    "fields": [
                        {
                            "type": "UInt64",
                            "field": "event_id",
                            "alias": "puppy_to_event_id",
                        }
                    ]
                },
                "attributes": [
                    {"type": "String", "field": "call_type", "alias": "call_type"},
                    {
                        "type": "DateTime",
                        "field": "event_datetime",
                        "alias": "event_datetime",
                    },
                ],
            }
        ],
    }

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

    # STEP 2: Analyze query using Analyzer Visitor
    print("\n[STEP 2] Analyzing query for optimization...")
    analyzer = QueryAnalyzerVisitor()
    analyzer.visit(ast)
    analysis = analyzer.get_analysis()

    print("\nQuery Analysis:")
    for key, value in analysis.items():
        print(f"  {key}: {value}")

    # STEP 3: Generate SQL using SQL Generator Visitor
    print("\n[STEP 3] Generating optimized SQL with filter push-down...")
    sql_generator = SQLGeneratorVisitor(graph_schema)
    sql_generator.visit(ast)
    sql = sql_generator.generate_sql()

    print("\nGenerated SQL:")
    print("-" * 80)
    print(sql)


# def demo_complex_query():
#     """More complex example with multiple traversals"""

#     graph_schema = {
#         "vertex_tables": {
#             "User": "users",
#             "Product": "products",
#             "Category": "categories",
#         },
#         "edges": {
#             "purchased": {"table": "purchases", "target_table": "products"},
#             "belongs_to": {"table": "product_categories", "target_table": "categories"},
#         },
#     }

#     print("\n\n" + "=" * 80)
#     print("COMPLEX QUERY EXAMPLE")
#     print("=" * 80)
#     print("\nQuery: Find categories of products purchased by users over 25")
#     print("g.V().has('User', 'age', gt(25)).out('purchased').out('belongs_to')")

#     builder = GremlinASTBuilder()
#     ast = (
#         builder.V()
#         .has("User", "age", Predicate(PredicateOp.GT, 25))
#         .out("purchased")
#         .out("belongs_to")
#         .values("name")
#         .build()
#     )

#     sql_generator = SQLGeneratorVisitor(graph_schema)
#     sql_generator.visit(ast)
#     sql = sql_generator.generate_sql()

#     print("\nGenerated SQL:")
#     print("-" * 80)
#     print(sql)
#     print("-" * 80)


if __name__ == "__main__":
    demo_hybrid_approach()
    # demo_complex_query()
