"""
Visitor pattern implementations for processing Gremlin AST nodes
"""

from typing import Any, List, Dict, Optional
from abc import ABC, abstractmethod

# Try relative imports first (when imported as a module)
try:
    from .ast_nodes import ASTNode, Predicate
except ImportError:
    # Fall back to absolute imports (when run directly)
    from ast_nodes import ASTNode, Predicate


class GremlinVisitor(ABC):
    """Abstract visitor for processing AST nodes"""

    @abstractmethod
    def visit(self, node: ASTNode):
        """Visit an AST node"""
        pass


class SQLGeneratorVisitor(GremlinVisitor):
    """
    Visitor that generates optimized SQL with filter push-down.
    Avoids unnecessary self-joins when all tables are the same.
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

        # Aggregation support
        self.group_by_fields: List[str] = []
        self.aggregations: List[Dict[str, Any]] = []
        self.order_by_clauses: List[str] = []
        self.limit_value: Optional[int] = None
        self.has_aggregation = False
        self.pending_by_args: List[Any] = []  # Store by() args for next step

    def visit(self, node: ASTNode):
        """Main visit method that dispatches to specific handlers"""
        if node is None:
            return

        # Dispatch based on step type
        method_name = f"visit_{node.step_type}"
        if hasattr(self, method_name):
            getattr(self, method_name)(node)
        else:
            raise NotImplementedError(
                f"Step '{node.step_type}' not implemented"
            )

        # Continue to next step
        if node.next_step:
            self.visit(node.next_step)

    def visit_V(self, node: ASTNode):
        """Handle V() - start at vertices"""
        label = self._get_vertex_label_from_context(node)
        vertex_config = self._get_vertex_config(label)

        if vertex_config:
            table_source = vertex_config["oneToOne"]["tableSource"]
            schema = table_source["schema"]
            table = table_source["table"]
            table_name = f"{schema}.{table}"
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
            ids = (
                node.args[0]
                if isinstance(node.args[0], list)
                else [node.args[0]]
            )
            id_list = ", ".join(f"'{id}'" for id in ids)
            self.where_clauses.append(f"{alias}.{id_field} IN ({id_list})")

    def visit_has(self, node: ASTNode):
        """Handle has() - filter vertices/edges by property"""
        args = node.args

        if len(args) == 3:
            # has(label, key, predicate)
            _label, key, predicate = args

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
            edge_schema = edge_table_source["schema"]
            edge_tbl = edge_table_source["table"]
            edge_table = f"{edge_schema}.{edge_tbl}"
            from_id_field = edge_config["fromId"]["fields"][0]["field"]
            to_id_field = edge_config["toId"]["fields"][0]["field"]

            # Get target vertex configuration
            target_vertex_label = edge_config["toVertex"]
            target_vertex_config = self._get_vertex_config(
                target_vertex_label
            )

            if target_vertex_config:
                target_table_source = target_vertex_config["oneToOne"][
                    "tableSource"
                ]
                target_schema = target_table_source["schema"]
                target_tbl = target_table_source["table"]
                target_table = f"{target_schema}.{target_tbl}"
                target_id_field = target_vertex_config["oneToOne"]["id"][
                    "fields"
                ][0]["field"]
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

            # Join edge table - use current vertex ID field
            source_id_field = self.current_vertex_id_field or "id"
            self.joins.append(
                f"INNER JOIN {edge_table} AS {edge_alias} "
                f"ON {self.current_table_alias}.{source_id_field} = "
                f"{edge_alias}.{from_id_field}"
            )

            # Join target vertex table
            self.joins.append(
                f"INNER JOIN {target_table} AS {vertex_alias} "
                f"ON {edge_alias}.{to_id_field} = "
                f"{vertex_alias}.{target_id_field}"
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
            edge_schema = edge_table_source["schema"]
            edge_tbl = edge_table_source["table"]
            edge_table = f"{edge_schema}.{edge_tbl}"
            from_id_field = edge_config["fromId"]["fields"][0]["field"]
            to_id_field = edge_config["toId"]["fields"][0]["field"]

            # Get source vertex configuration
            source_vertex_label = edge_config["fromVertex"]
            source_vertex_config = self._get_vertex_config(
                source_vertex_label
            )

            if source_vertex_config:
                source_table_source = source_vertex_config["oneToOne"][
                    "tableSource"
                ]
                source_schema = source_table_source["schema"]
                source_tbl = source_table_source["table"]
                source_table = f"{source_schema}.{source_tbl}"
                source_id_field = source_vertex_config["oneToOne"]["id"][
                    "fields"
                ][0]["field"]
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

            # Join edge table - use current vertex ID field
            current_id_field = self.current_vertex_id_field or "id"
            self.joins.append(
                f"INNER JOIN {edge_table} AS {edge_alias} "
                f"ON {self.current_table_alias}.{current_id_field} = "
                f"{edge_alias}.{to_id_field}"
            )

            self.joins.append(
                f"INNER JOIN {source_table} AS {vertex_alias} "
                f"ON {edge_alias}.{from_id_field} = "
                f"{vertex_alias}.{source_id_field}"
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

    def visit_group(self, node: ASTNode):
        """
        Handle group() - initiates aggregation mode
        Following by() steps will define group by fields and aggregations
        """
        self.has_aggregation = True
        # Process next step to collect by() modulator args
        if node.next_step and node.next_step.step_type == "by":
            # Collect all consecutive by() steps
            current = node.next_step
            by_steps = []
            while current and current.step_type == "by":
                by_steps.append(current.args)
                current = current.next_step

            # First by() defines GROUP BY fields
            if len(by_steps) >= 1:
                group_fields = by_steps[0]
                for field in group_fields:
                    self.group_by_fields.append(
                        f"{self.current_table_alias}.{field}"
                    )

            # Second by() defines aggregations (if present)
            if len(by_steps) >= 2:
                agg_specs = by_steps[1]
                # Parse aggregation specifications
                # Format: ["count", "sum"] or similar
                for agg_type in agg_specs:
                    if agg_type == "count":
                        self.aggregations.append(
                            {"type": "COUNT", "field": "*", "alias": "count"}
                        )
                    elif agg_type == "sum":
                        # Sum will be processed by visit_sum
                        pass

    def visit_by(self, node: ASTNode):
        """
        Handle by() - modulator for group/order operations
        Stores args for parent step to process
        """
        # Store the args for the parent step to use
        self.pending_by_args = node.args

    def visit_count(self, node: ASTNode):
        """Handle count() - count aggregation"""
        if self.has_aggregation:
            self.aggregations.append(
                {"type": "COUNT", "field": "*", "alias": "call_count"}
            )
        else:
            # Standalone count
            self.select_columns = ["COUNT(*)"]

    def visit_sum(self, node: ASTNode):
        """Handle sum() - sum aggregation"""
        field = node.args[0] if node.args else None
        if field and self.has_aggregation:
            full_field = f"{self.current_table_alias}.{field}"
            self.aggregations.append(
                {
                    "type": "SUM",
                    "field": full_field,
                    "alias": f"total_{field}",
                }
            )

    def visit_order(self, node: ASTNode):
        """
        Handle order() - ordering step
        Expects by() modulator to specify field and direction
        """
        # Check for following by() step
        if node.next_step and node.next_step.step_type == "by":
            by_node = node.next_step
            if len(by_node.args) >= 2:
                field = by_node.args[0]
                direction = by_node.args[1].upper()
                self.order_by_clauses.append(f"{field} {direction}")
            elif len(by_node.args) == 1:
                field = by_node.args[0]
                self.order_by_clauses.append(f"{field} DESC")

    def visit_limit(self, node: ASTNode):
        """Handle limit() - result limiting"""
        if node.args and len(node.args) > 0:
            self.limit_value = int(node.args[0])

    def visit_select(self, node: ASTNode):
        """Handle select() - select specific keys"""
        keys = node.args
        if not self.has_aggregation:
            self.select_columns = [
                f"{self.current_table_alias}.{key}" for key in keys
            ]

    def visit_as(self, node: ASTNode):
        """Handle as() - step labeling (for future use)"""
        # This could be used for more complex queries with labels
        pass

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
        """Generate final SQL query with support for aggregations"""

        # Build SELECT clause
        if self.has_aggregation:
            # Build SELECT with group by fields and aggregations
            select_items = []

            # Add group by fields with aliases
            for field in self.group_by_fields:
                field_name = field.split(".")[-1]  # Extract field name
                select_items.append(f"{field} AS {field_name}")

            # Add aggregations
            for agg in self.aggregations:
                if agg["type"] == "COUNT":
                    select_items.append(
                        f"COUNT({agg['field']}) AS {agg['alias']}"
                    )
                elif agg["type"] == "SUM":
                    select_items.append(
                        f"SUM({agg['field']}) AS {agg['alias']}"
                    )

            select_clause = f"SELECT {', '.join(select_items)}"
        else:
            select_clause = f"SELECT {', '.join(self.select_columns)}"

        from_clause = f"FROM {self.tables[0]}"
        sql_parts = [select_clause, from_clause]

        # Add JOINs
        if self.joins:
            sql_parts.extend(self.joins)

        # Add WHERE clause
        if self.where_clauses:
            where_clause = f"WHERE {' AND '.join(self.where_clauses)}"
            sql_parts.append(where_clause)

        # Add GROUP BY clause
        if self.group_by_fields:
            group_by_clause = f"GROUP BY {', '.join(self.group_by_fields)}"
            sql_parts.append(group_by_clause)

        # Add ORDER BY clause
        if self.order_by_clauses:
            order_by_clause = f"ORDER BY {', '.join(self.order_by_clauses)}"
            sql_parts.append(order_by_clause)

        # Add LIMIT clause
        if self.limit_value is not None:
            limit_clause = f"LIMIT {self.limit_value}"
            sql_parts.append(limit_clause)

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
        if self.estimated_selectivity < 0.5:
            return "Moderately selective - SQL push-down recommended"
        return "Low selectivity - consider adding more filters"
