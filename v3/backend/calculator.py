"""
A small, safe calculator for the model. It parses the expression instead of running it, so only
numbers, + - * / % **, brackets and a short list of maths functions are possible.
"""

import ast
import math
import operator

MAX_LENGTH = 200

_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {
    "round": round, "abs": abs, "min": min, "max": max, "sqrt": math.sqrt,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "acos": math.acos, "asin": math.asin, "atan": math.atan,
    "radians": math.radians, "degrees": math.degrees,
    "log": math.log, "log10": math.log10,
}
_CONSTANTS = {"pi": math.pi}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value

    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
            raise ValueError("That power is too large.")
        return _BINARY[type(node.op)](left, right)

    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCTIONS and not node.keywords):
        return _FUNCTIONS[node.func.id](*[_eval(arg) for arg in node.args])

    raise ValueError("Only numbers, + - * / % **, brackets and basic maths functions are allowed.")


def calculate(expression):
    """Evaluate an arithmetic expression. Raises ValueError with a readable message."""
    text = (expression or "").strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    if not text:
        raise ValueError("Empty expression.")
    if len(text) > MAX_LENGTH:
        raise ValueError("Expression is too long.")

    try:
        result = _eval(ast.parse(text, mode="eval"))
    except ZeroDivisionError:
        raise ValueError("Division by zero.") from None
    except SyntaxError:
        raise ValueError("Couldn't read that expression.") from None
    except (TypeError, OverflowError) as exc:
        raise ValueError(f"Couldn't calculate that: {exc}") from None

    if isinstance(result, float):
        if not math.isfinite(result):
            raise ValueError("The result isn't a finite number.")
        result = round(result, 6)
    return result
