"""
AST (Abstract Syntax Tree) node definitions for Gremlin query representation
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict
from enum import Enum


class PredicateOp(Enum):
    """Predicate operators for filtering"""

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
        """Convert predicate operator to SQL operator"""
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

    def hasLabel(self, label: str):
        """Filter vertices by label"""
        return self._add_step("hasLabel", [label])

    def out(self, edge_label: str):
        """Traverse outgoing edges"""
        return self._add_step("out", [edge_label])

    def outE(self, edge_label: str):
        """Alias for out() - traverse outgoing edges"""
        return self.out(edge_label)

    def in_(self, edge_label: str):
        """Traverse incoming edges"""
        return self._add_step("in", [edge_label])

    def inE(self, edge_label: str):
        """Alias for in_() - traverse incoming edges"""
        return self.in_(edge_label)

    def inV(self):
        """From edge, traverse to incoming vertex"""
        return self._add_step("inV", [])

    def outV(self):
        """From edge, traverse to outgoing vertex"""
        return self._add_step("outV", [])

    def values(self, *property_keys):
        """Get property values"""
        return self._add_step("values", list(property_keys))

    def group(self):
        """Group step for aggregation"""
        return self._add_step("group", [])

    def by(self, *args):
        """By step for grouping/projection modulator"""
        return self._add_step("by", list(args))

    def count(self):
        """Count aggregation"""
        return self._add_step("count", [])

    def sum(self, property_key: str = None):
        """Sum aggregation"""
        return self._add_step("sum", [property_key] if property_key else [])

    def order(self):
        """Order step for sorting"""
        return self._add_step("order", [])

    def limit(self, n: int):
        """Limit step to restrict results"""
        return self._add_step("limit", [n])

    def select(self, *keys):
        """Select specific keys from the traversal"""
        return self._add_step("select", list(keys))

    def as_(self, label: str):
        """Label a step for later reference"""
        return self._add_step("as", [label])

    def repeat(self, traversal):
        """Repeat a traversal pattern"""
        return self._add_step("repeat", [traversal])

    def times(self, n: int):
        """Specify number of times to repeat"""
        return self._add_step("times", [n])

    def emit(self):
        """Emit intermediate results during repeat"""
        return self._add_step("emit", [])

    def path(self):
        """Collect the full path traversed"""
        return self._add_step("path", [])

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
