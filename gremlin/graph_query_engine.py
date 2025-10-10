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
        table_name = self.graph_schema["vertex_tables"].get(label, "vertices")

        alias = f"v{self.table_counter}"
        self.table_counter += 1

        self.tables.append(f"{table_name} AS {alias}")
        self.current_table_alias = alias

        # If specific IDs provided
        if node.args and node.args[0]:
            ids = node.args[0] if isinstance(node.args[0], list) else [node.args[0]]
            id_list = ", ".join(f"'{id}'" for id in ids)
            self.where_clauses.append(f"{alias}.id IN ({id_list})")

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

        # Get edge table and target vertex table from schema
        edge_info = self.graph_schema["edges"].get(edge_label, {})
        edge_table = edge_info.get("table", "edges")
        target_table = edge_info.get("target_table", "vertices")

        # Create aliases
        edge_alias = f"e{self.table_counter}"
        self.table_counter += 1
        vertex_alias = f"v{self.table_counter}"
        self.table_counter += 1

        # Join edge table
        self.joins.append(
            f"INNER JOIN {edge_table} AS {edge_alias} "
            f"ON {self.current_table_alias}.id = {edge_alias}.from_id "
            f"AND {edge_alias}.label = '{edge_label}'"
        )

        # Join target vertex table
        self.joins.append(
            f"INNER JOIN {target_table} AS {vertex_alias} "
            f"ON {edge_alias}.to_id = {vertex_alias}.id"
        )

        self.current_table_alias = vertex_alias

    def visit_in(self, node: ASTNode):
        """Handle in() - traverse incoming edges"""
        edge_label = node.args[0]

        edge_info = self.graph_schema["edges"].get(edge_label, {})
        edge_table = edge_info.get("table", "edges")
        source_table = edge_info.get("source_table", "vertices")

        edge_alias = f"e{self.table_counter}"
        self.table_counter += 1
        vertex_alias = f"v{self.table_counter}"
        self.table_counter += 1

        self.joins.append(
            f"INNER JOIN {edge_table} AS {edge_alias} "
            f"ON {self.current_table_alias}.id = {edge_alias}.to_id "
            f"AND {edge_alias}.label = '{edge_label}'"
        )

        self.joins.append(
            f"INNER JOIN {source_table} AS {vertex_alias} "
            f"ON {edge_alias}.from_id = {vertex_alias}.id"
        )

        self.current_table_alias = vertex_alias

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
    Query: g.V().has('User', 'age', gt(25)).out('purchased').has('Product', 'price', lt(100))
    """

    # Define graph schema (mapping to relational tables)
    graph_schema = {
        "vertex_tables": {"User": "users", "Product": "products"},
        "edges": {"purchased": {"table": "purchases", "target_table": "products"}},
    }

    print("=" * 80)
    print("HYBRID APPROACH: Simple AST + Visitor Pattern")
    print("=" * 80)

    # STEP 1: Build AST using simple chained approach
    print("\n[STEP 1] Building AST from Gremlin-like API...")
    builder = GremlinASTBuilder()
    ast = (
        builder.V()
        .has("User", "age", Predicate(PredicateOp.GT, 25))
        .out("purchased")
        .has("Product", "price", Predicate(PredicateOp.LT, 100))
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


def demo_complex_query():
    """More complex example with multiple traversals"""

    graph_schema = {
        "vertex_tables": {
            "User": "users",
            "Product": "products",
            "Category": "categories",
        },
        "edges": {
            "purchased": {"table": "purchases", "target_table": "products"},
            "belongs_to": {"table": "product_categories", "target_table": "categories"},
        },
    }

    print("\n\n" + "=" * 80)
    print("COMPLEX QUERY EXAMPLE")
    print("=" * 80)
    print("\nQuery: Find categories of products purchased by users over 25")
    print("g.V().has('User', 'age', gt(25)).out('purchased').out('belongs_to')")

    builder = GremlinASTBuilder()
    ast = (
        builder.V()
        .has("User", "age", Predicate(PredicateOp.GT, 25))
        .out("purchased")
        .out("belongs_to")
        .values("name")
        .build()
    )

    sql_generator = SQLGeneratorVisitor(graph_schema)
    sql_generator.visit(ast)
    sql = sql_generator.generate_sql()

    print("\nGenerated SQL:")
    print("-" * 80)
    print(sql)
    print("-" * 80)


if __name__ == "__main__":
    demo_hybrid_approach()
    # demo_complex_query()
