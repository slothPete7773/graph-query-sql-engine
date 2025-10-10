"""
Approaches to convert Gremlin API calls to Abstract Syntax Tree (AST)
Example: g.V().has('User', 'age', gt(25)).out('purchased').has('Product', 'price', lt(100))
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional
import json


# ============================================================================
# APPROACH 1: Simple Node-Based AST with Method Chaining
# ============================================================================


@dataclass
class ASTNode:
    """Represents a single step in the Gremlin traversal"""

    method: str
    args: List[Any] = field(default_factory=list)
    kwargs: dict = field(default_factory=dict)
    next_step: Optional["ASTNode"] = None

    def to_dict(self):
        result = {"method": self.method, "args": self.args, "kwargs": self.kwargs}
        if self.next_step:
            result["next"] = self.next_step.to_dict()
        return result


class GremlinASTBuilder:
    """Builder pattern for constructing AST from Gremlin calls"""

    def __init__(self):
        self.root = None
        self.current = None

    def add_step(self, method: str, *args, **kwargs):
        node = ASTNode(method=method, args=list(args), kwargs=kwargs)

        if self.root is None:
            self.root = node
        else:
            self.current.next_step = node

        self.current = node
        return self

    def build(self):
        return self.root


# ============================================================================
# APPROACH 3: Visitor Pattern with AST (Best for Complex Transformations)
# ============================================================================


class Predicate:
    def __init__(self, operator: str, value: Any):
        self.operator = operator
        self.value = value


class GremlinStep:
    """Base class for all Gremlin steps"""

    def accept(self, visitor):
        pass


class VertexStep(GremlinStep):
    def __init__(self, ids: List[Any] = None):
        self.ids = ids or []

    def accept(self, visitor):
        return visitor.visit_vertex_step(self)


class HasStep(GremlinStep):
    def __init__(self, label: str, key: str, predicate: Predicate):
        self.label = label
        self.key = key
        self.predicate = predicate

    def accept(self, visitor):
        return visitor.visit_has_step(self)


class OutStep(GremlinStep):
    def __init__(self, edge_label: str):
        self.edge_label = edge_label

    def accept(self, visitor):
        return visitor.visit_out_step(self)


class Traversal:
    def __init__(self):
        self.steps: List[GremlinStep] = []

    def add_step(self, step: GremlinStep):
        self.steps.append(step)
        return self


class ASTVisitor:
    """Visitor to transform AST"""

    def visit_vertex_step(self, step: VertexStep):
        return {"type": "V", "ids": step.ids}

    def visit_has_step(self, step: HasStep):
        return {
            "type": "has",
            "label": step.label,
            "key": step.key,
            "predicate": {
                "operator": step.predicate.operator,
                "value": step.predicate.value,
            },
        }

    def visit_out_step(self, step: OutStep):
        return {"type": "out", "edge_label": step.edge_label}


# ============================================================================
# DEMONSTRATION
# ============================================================================


def demo_approach_1():
    """Simple chained AST"""
    print("=== APPROACH 1: Simple Node-Based AST ===")
    builder = GremlinASTBuilder()
    ast = (
        builder.add_step("V")
        .add_step("has", "User", "age", predicate={"gt": 25})
        .add_step("out", "purchased")
        .add_step("has", "Product", "price", predicate={"lt": 100})
        .build()
    )

    print(json.dumps(ast.to_dict(), indent=2))


def devmo_visitor_pattern():
    """Visitor pattern"""
    print("\n=== APPROACH 3: Visitor Pattern ===")
    traversal = Traversal()
    traversal.add_step(VertexStep())
    traversal.add_step(HasStep("User", "age", Predicate("gt", 25)))
    traversal.add_step(OutStep("purchased"))

    visitor = ASTVisitor()
    ast = [step.accept(visitor) for step in traversal.steps]
    print(json.dumps(ast, indent=2))


if __name__ == "__main__":
    # demo_approach_1()
    devmo_visitor_pattern()
