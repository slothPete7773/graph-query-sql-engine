"""
Visitor pattern implementations for processing Gremlin AST nodes
— ClickHouse-compatible SQL generation
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
    ClickHouse-compatible (no WITH RECURSIVE; see _generate_clickhouse_recursive_sql()).
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

        # Recursive traversal support
        self.repeat_traversal: Optional[ASTNode] = None
        self.repeat_times: Optional[int] = None
        self.repeat_emit: bool = False
        self.collect_path: bool = False
        self.use_recursive_cte: bool = False  # stays True to trigger ClickHouse path

    def visit(self, node: ASTNode):
        """Main visit method that dispatches to specific handlers"""
        if node is None:
            return

        method_name = f"visit_{node.step_type}"
        if hasattr(self, method_name):
            getattr(self, method_name)(node)
        else:
            raise NotImplementedError(f"Step '{node.step_type}' not implemented")

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
            # ClickHouse allows db.table form
            table_name = f"{schema}.{table}"
            id_field = vertex_config["oneToOne"]["id"]["fields"][0]["field"]
        else:
            table_name = "vertices"
            id_field = "id"

        alias = f"v{self.table_counter}"
        self.table_counter += 1

        # ClickHouse supports AS for table aliases
        self.tables.append(f"{table_name} AS {alias}")
        self.current_table_alias = alias
        self.current_vertex_id_field = id_field
        self.current_table_name = table_name

        # If specific IDs provided
        if node.args and node.args[0]:
            ids = node.args[0] if isinstance(node.args[0], list) else [node.args[0]]
            # Single-quote string values for CH. Numeric literals are fine too.
            id_list = ", ".join(self._format_sql_value(id_) for id_ in ids)
            self.where_clauses.append(f"{alias}.{id_field} IN ({id_list})")

    def visit_has(self, node: ASTNode):
        """Handle has() - filter vertices/edges by property"""
        args = node.args
        if len(args) == 3:
            # has(label, key, predicate)
            _label, key, predicate = args
            if isinstance(predicate, Predicate):
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
        edge_config = self._get_edge_config(edge_label)

        if edge_config:
            edge_table_source = edge_config["tableSource"]
            edge_schema = edge_table_source["schema"]
            edge_tbl = edge_table_source["table"]
            edge_table = f"{edge_schema}.{edge_tbl}"
            from_id_field = edge_config["fromId"]["fields"][0]["field"]
            to_id_field = edge_config["toId"]["fields"][0]["field"]

            target_vertex_label = edge_config["toVertex"]
            target_vertex_config = self._get_vertex_config(target_vertex_label)

            if target_vertex_config:
                target_table_source = target_vertex_config["oneToOne"]["tableSource"]
                target_schema = target_table_source["schema"]
                target_tbl = target_table_source["table"]
                target_table = f"{target_schema}.{target_tbl}"
                target_id_field = target_vertex_config["oneToOne"]["id"]["fields"][0][
                    "field"
                ]
            else:
                target_table = "vertices"
                target_id_field = "id"
        else:
            edge_table = "edges"
            from_id_field = "from_id"
            to_id_field = "to_id"
            target_table = "vertices"
            target_id_field = "id"

        if self.current_table_name == edge_table == target_table:
            # same-table optimization
            self.current_vertex_id_field = target_id_field
        else:
            edge_alias = f"e{self.table_counter}"
            self.table_counter += 1
            vertex_alias = f"v{self.table_counter}"
            self.table_counter += 1

            source_id_field = self.current_vertex_id_field or "id"
            # ClickHouse supports INNER JOIN ... ON ...
            self.joins.append(
                f"INNER JOIN {edge_table} AS {edge_alias} "
                f"ON {self.current_table_alias}.{source_id_field} = {edge_alias}.{from_id_field}"
            )
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
        edge_config = self._get_edge_config(edge_label)

        if edge_config:
            edge_table_source = edge_config["tableSource"]
            edge_schema = edge_table_source["schema"]
            edge_tbl = edge_table_source["table"]
            edge_table = f"{edge_schema}.{edge_tbl}"
            from_id_field = edge_config["fromId"]["fields"][0]["field"]
            to_id_field = edge_config["toId"]["fields"][0]["field"]

            source_vertex_label = edge_config["fromVertex"]
            source_vertex_config = self._get_vertex_config(source_vertex_label)

            if source_vertex_config:
                source_table_source = source_vertex_config["oneToOne"]["tableSource"]
                source_schema = source_table_source["schema"]
                source_tbl = source_table_source["table"]
                source_table = f"{source_schema}.{source_tbl}"
                source_id_field = source_vertex_config["oneToOne"]["id"]["fields"][0][
                    "field"
                ]
            else:
                source_table = "vertices"
                source_id_field = "id"
        else:
            edge_table = "edges"
            from_id_field = "from_id"
            to_id_field = "to_id"
            source_table = "vertices"
            source_id_field = "id"

        if self.current_table_name == edge_table == source_table:
            self.current_vertex_id_field = source_id_field
        else:
            edge_alias = f"e{self.table_counter}"
            self.table_counter += 1
            vertex_alias = f"v{self.table_counter}"
            self.table_counter += 1

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

    def visit_group(self, node: ASTNode):
        """Handle group() - initiates aggregation mode"""
        self.has_aggregation = True
        if node.next_step and node.next_step.step_type == "by":
            current = node.next_step
            by_steps = []
            while current and current.step_type == "by":
                by_steps.append(current.args)
                current = current.next_step

            if len(by_steps) >= 1:
                group_fields = by_steps[0]
                for field in group_fields:
                    self.group_by_fields.append(f"{self.current_table_alias}.{field}")

            if len(by_steps) >= 2:
                agg_specs = by_steps[1]
                for agg_type in agg_specs:
                    if agg_type == "count":
                        self.aggregations.append(
                            {"type": "COUNT", "field": "*", "alias": "count"}
                        )
                    elif agg_type == "sum":
                        pass  # sum handled by visit_sum

    def visit_by(self, node: ASTNode):
        self.pending_by_args = node.args

    def visit_count(self, node: ASTNode):
        if self.has_aggregation:
            self.aggregations.append(
                {"type": "COUNT", "field": "*", "alias": "call_count"}
            )
        else:
            self.select_columns = ["COUNT(*)"]

    def visit_sum(self, node: ASTNode):
        field = node.args[0] if node.args else None
        if field and self.has_aggregation:
            full_field = f"{self.current_table_alias}.{field}"
            self.aggregations.append(
                {"type": "SUM", "field": full_field, "alias": f"total_{field}"}
            )

    def visit_order(self, node: ASTNode):
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
        if node.args and len(node.args) > 0:
            self.limit_value = int(node.args[0])

    def visit_select(self, node: ASTNode):
        keys = node.args
        if not self.has_aggregation:
            self.select_columns = [f"{self.current_table_alias}.{key}" for key in keys]

    def visit_as(self, node: ASTNode):
        pass

    def visit_hasLabel(self, node: ASTNode):
        label = node.args[0] if node.args else None
        if label:
            pass

    def visit_outE(self, node: ASTNode):
        self.visit_out(node)

    def visit_inV(self, node: ASTNode):
        pass

    def visit_outV(self, node: ASTNode):
        pass

    def visit_inE(self, node: ASTNode):
        self.visit_in(node)

    def visit_repeat(self, node: ASTNode):
        if node.args and len(node.args) > 0:
            self.repeat_traversal = node.args[0]
            self.use_recursive_cte = True  # triggers ClickHouse-style expansion

    def visit_times(self, node: ASTNode):
        if node.args and len(node.args) > 0:
            self.repeat_times = int(node.args[0])

    def visit_emit(self, node: ASTNode):
        self.repeat_emit = True

    def visit_path(self, node: ASTNode):
        self.collect_path = True

    def _get_vertex_label_from_context(self, node: ASTNode) -> str:
        current = node.next_step
        while current:
            if current.step_type == "hasLabel" and current.args:
                return current.args[0]
            if current.step_type == "has" and len(current.args) == 3:
                return current.args[0]
            current = current.next_step
        return "default"

    def _get_vertex_config(self, label: str) -> Optional[Dict[str, Any]]:
        if "vertices" in self.graph_schema:
            for vertex in self.graph_schema["vertices"]:
                if vertex["label"] == label:
                    return vertex
        return None

    def _get_edge_config(self, label: str) -> Optional[Dict[str, Any]]:
        if "edges" in self.graph_schema:
            for edge in self.graph_schema["edges"]:
                if edge["label"] == label:
                    return edge
        return None

    def _format_sql_value(self, value: Any) -> str:
        """Format Python value for ClickHouse SQL"""
        if isinstance(value, str):
            # escape single quotes by doubling
            v = value.replace("'", "''")
            return f"'{v}'"
        if value is None:
            return "NULL"
        return str(value)

    def _generate_clickhouse_recursive_sql(self) -> str:
        """
        Generate ClickHouse-compatible SQL for recursive-ish traversal patterns.

        Strategy:
          - Expand up to N hops with UNION ALL (depth 1..N).
          - Use self-joins per hop.
          - Optionally collect path as an Array(...) (works with [] literal).
        """
        base_filters = []
        for where_clause in self.where_clauses:
            base_filters.append(where_clause)

        # Extract simple filters from repeat traversal (only has() predicates)
        repeat_filters = []
        if self.repeat_traversal:
            repeat_node = self.repeat_traversal
            while repeat_node:
                if repeat_node.step_type == "has" and len(repeat_node.args) >= 2:
                    key = (
                        repeat_node.args[0]
                        if len(repeat_node.args) == 2
                        else repeat_node.args[1]
                    )
                    value_or_pred = repeat_node.args[-1]
                    if isinstance(value_or_pred, Predicate):
                        op = value_or_pred.to_sql_operator()
                        val = self._format_sql_value(value_or_pred.value)
                        repeat_filters.append(f"{key} {op} {val}")
                    else:
                        val = self._format_sql_value(value_or_pred)
                        repeat_filters.append(f"{key} = {val}")
                repeat_node = repeat_node.next_step

        parts: List[str] = []
        depth_limit = self.repeat_times or 3
        id_field = self.current_vertex_id_field or "id"
        table_name = self.current_table_name or (
            self.tables[0].split(" AS ")[0] if self.tables else "vertices"
        )

        # Build UNION ALL chain for depths 1..N
        for depth in range(1, depth_limit + 1):
            if depth > 1:
                parts.append("UNION ALL")

            select_cols = f"t{depth-1}.*"
            select_prefix = f"SELECT {depth} AS depth"

            if self.collect_path:
                if depth == 1:
                    path_expr = f"[t0.{id_field}]"
                else:
                    path_items = ", ".join([f"t{i}.{id_field}" for i in range(depth)])
                    path_expr = f"[{path_items}]"
                select_prefix += f", {path_expr} AS path"

            parts.append(f"{select_prefix}, {select_cols}")
            parts.append(f"FROM {table_name} AS t0")

            # base filters at depth 1 (rewrite alias if needed)
            if depth == 1 and base_filters:
                rewritten = [
                    f.replace(self.current_table_alias or "v0", "t0")
                    for f in base_filters
                ]
                parts.append(f"WHERE {' AND '.join(rewritten)}")

            # add hops as self-joins on id_field
            for hop in range(1, depth):
                join_cond = [f"t{hop-1}.{id_field} = t{hop}.{id_field}"]
                if repeat_filters:
                    # apply repeat filters to the joined level
                    join_cond.extend([f"t{hop}.{filt}" for filt in repeat_filters])
                parts.append(
                    f"INNER JOIN {table_name} AS t{hop} ON " + " AND ".join(join_cond)
                )

        # Wrap to allow ORDER/LIMIT
        wrapped = "(\n" + "\n".join(parts) + "\n)"
        final = [f"SELECT * FROM {wrapped}"]

        if self.order_by_clauses:
            final.append(f"ORDER BY {', '.join(self.order_by_clauses)}")
        else:
            final.append("ORDER BY depth")

        if self.limit_value is not None:
            # ClickHouse supports simple LIMIT N
            final.append(f"LIMIT {self.limit_value}")

        return "\n".join(final)

    def generate_sql(self) -> str:
        """Generate final SQL query; uses ClickHouse path for repeat()/times()."""
        # If repeat()/times() pattern was used, switch to ClickHouse expansion
        if self.use_recursive_cte:
            return self._generate_clickhouse_recursive_sql()

        # SELECT clause
        if self.has_aggregation:
            select_items = []
            for field in self.group_by_fields:
                field_name = field.split(".")[-1]
                select_items.append(f"{field} AS {field_name}")
            for agg in self.aggregations:
                if agg["type"] == "COUNT":
                    select_items.append(f"COUNT({agg['field']}) AS {agg['alias']}")
                elif agg["type"] == "SUM":
                    select_items.append(f"SUM({agg['field']}) AS {agg['alias']}")
            select_clause = f"SELECT {', '.join(select_items)}"
        else:
            select_clause = f"SELECT {', '.join(self.select_columns)}"

        # FROM + JOINs
        from_clause = f"FROM {self.tables[0]}"
        sql_parts = [select_clause, from_clause]
        if self.joins:
            sql_parts.extend(self.joins)

        # WHERE
        if self.where_clauses:
            sql_parts.append(f"WHERE {' AND '.join(self.where_clauses)}")

        # GROUP BY
        if self.group_by_fields:
            sql_parts.append(f"GROUP BY {', '.join(self.group_by_fields)}")

        # ORDER BY
        if self.order_by_clauses:
            sql_parts.append(f"ORDER BY {', '.join(self.order_by_clauses)}")

        # LIMIT
        if self.limit_value is not None:
            sql_parts.append(f"LIMIT {self.limit_value}")

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
        if node is None:
            return

        if node.step_type == "has":
            self.vertex_filters.append(node.args)
            if len(node.args) == 3 and isinstance(node.args[2], Predicate):
                self.estimated_selectivity *= 0.1
        elif node.step_type in ["out", "in"]:
            self.edge_traversals.append(node.args[0])

        if node.next_step:
            self.visit(node.next_step)

    def get_analysis(self) -> Dict[str, Any]:
        return {
            "num_filters": len(self.vertex_filters),
            "num_traversals": len(self.edge_traversals),
            "estimated_selectivity": self.estimated_selectivity,
            "recommendation": self._get_recommendation(),
        }

    def _get_recommendation(self) -> str:
        if self.estimated_selectivity < 0.01:
            return "Highly selective query - good for SQL push-down"
        if self.estimated_selectivity < 0.5:
            return "Moderately selective - SQL push-down recommended"
        return "Low selectivity - consider adding more filters"
