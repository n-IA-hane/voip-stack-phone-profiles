# SPDX-License-Identifier: MIT
"""Fail-closed offline Smarty subset compiler. No evaluation of source Python/PHP.

The result uses only standard Jinja expressions and loopcontrols. This is not a
Smarty runtime: unsupported syntax is an explicit import error, never a blank.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import re


class UnsupportedSmarty(ValueError):
    """The source needs a construct whose semantics are not implemented."""


@dataclass(frozen=True)
class Expr:
    code: str
    guards: tuple[str, ...] = ()

    def isset(self) -> str:
        checks = [f"({g}) is defined" for g in self.guards]
        checks.extend([f"({self.code}) is defined", f"({self.code}) is not none"])
        return "(" + " and ".join(checks) + ")"

    def truth(self) -> str:
        c = self.code
        return (
            f"({self.isset()} and ({c}) != false and ({c}) != 0 "
            f"and ({c}) != '' and ({c}) != '0' and ({c}) != [] and ({c}) != {{}})"
        )

    def output(self) -> str:
        # PHP echo prints true as '1', false/null as '', while missing required
        # variables still reach StrictUndefined rather than becoming blank.
        c = self.code
        return f"(1 if ({c}) is sameas true else '' if ({c}) is sameas false or ({c}) is none else ({c}))"


TOKEN = re.compile(
    r"\s*(?:(\$[A-Za-z_]\w*)|([A-Za-z_]\w*)|([0-9]+(?:\.[0-9]+)?)|"
    r"('(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")|"
    r"(===|!==|==|!=|>=|<=|&&|\|\||=>|[.\[\](),:+*/%<>!|=-]))",
    re.S,
)


class ExpressionParser:
    def __init__(self, source: str, assigned: set[str] | None = None):
        self.tokens: list[tuple[str, str]] = []
        pos = 0
        self.assigned = assigned or set()
        while pos < len(source):
            m = TOKEN.match(source, pos)
            if not m:
                if not source[pos:].strip():
                    break
                raise UnsupportedSmarty(f"expression token: {source[pos : pos + 48]!r}")
            group = next(i for i, value in enumerate(m.groups()) if value is not None)
            self.tokens.append(
                (["var", "word", "number", "string", "op"][group], m.group(group + 1))
            )
            pos = m.end()
        self.i = 0

    def peek(self) -> str:
        return self.tokens[self.i][1] if self.i < len(self.tokens) else ""

    def pop(self, expected: str | None = None) -> tuple[str, str]:
        if self.i >= len(self.tokens):
            raise UnsupportedSmarty("incomplete expression")
        token = self.tokens[self.i]
        self.i += 1
        if expected is not None and token[1] != expected:
            raise UnsupportedSmarty(f"expected {expected!r}, got {token[1]!r}")
        return token

    def parse(self) -> Expr:
        e = self.expression()
        if self.peek():
            raise UnsupportedSmarty(f"unsupported expression suffix {self.peek()!r}")
        return e

    def expression(self, minimum: int = 0) -> Expr:
        kind, value = self.pop()
        if value in ("!", "not", "-", "+"):
            item = self.expression(60)
            left = Expr(
                f"(not {item.truth()})" if value in ("!", "not") else f"({value}{item.code})"
            )
        elif value == "(":
            left = self.expression()
            self.pop(")")
        elif value == "[":
            pairs: list[tuple[Expr | None, Expr]] = []
            while self.peek() != "]":
                a = self.expression()
                if self.peek() == "=>":
                    self.pop()
                    pairs.append((a, self.expression()))
                else:
                    pairs.append((None, a))
                if self.peek() != ",":
                    break
                self.pop()
            self.pop("]")
            if any(k is not None for k, _ in pairs):
                if any(k is None for k, _ in pairs):
                    raise UnsupportedSmarty("mixed keyed array")
                left = Expr("{" + ",".join(f"{k.code}:{v.code}" for k, v in pairs if k) + "}")
            else:
                left = Expr("[" + ",".join(v.code for _, v in pairs) + "]")
        elif kind == "var":
            name = value[1:]
            if name == "smarty":
                raise UnsupportedSmarty("Smarty special variable")
            left = Expr(f"__smarty.{name}" if name in self.assigned else name)
        elif kind == "string":
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError) as exc:
                raise UnsupportedSmarty("string literal") from exc
            if "$" in parsed or "`" in parsed:
                raise UnsupportedSmarty("interpolated string")
            left = Expr(json.dumps(parsed))
        elif kind == "number":
            left = Expr(value)
        elif kind == "word" and value.lower() in ("true", "false", "null"):
            left = Expr({"true": "true", "false": "false", "null": "none"}[value.lower()])
        elif kind == "word" and self.peek() == "(":
            self.pop()
            args = []
            while self.peek() != ")":
                args.append(self.expression())
                if self.peek() != ",":
                    break
                self.pop()
            self.pop(")")
            left = self.call(value, args)
        else:
            raise UnsupportedSmarty(f"expression atom {value!r}")
        precedence = {
            "or": 10,
            "||": 10,
            "and": 20,
            "&&": 20,
            "==": 30,
            "!=": 30,
            "eq": 30,
            "ne": 30,
            "gt": 30,
            "lt": 30,
            "ge": 30,
            "le": 30,
            ">": 30,
            "<": 30,
            ">=": 30,
            "<=": 30,
            "+": 40,
            "-": 40,
            "*": 50,
            "/": 50,
            "%": 50,
        }
        while self.peek():
            op = self.peek()
            if op in (".", "["):
                self.pop()
                if op == ".":
                    k, v = self.pop()
                    index = (
                        Expr(v)
                        if k == "number"
                        else Expr(f"__smarty.{v[1:]}" if v[1:] in self.assigned else v[1:])
                        if k == "var"
                        else Expr(json.dumps(v))
                    )
                else:
                    index = self.expression()
                    self.pop("]")
                left = Expr(f"{left.code}[{index.code}]", (*left.guards, left.code))
                continue
            if op == "|" and minimum <= 5:
                self.pop()
                name = self.pop()[1]
                args = []
                while self.peek() == ":":
                    self.pop()
                    args.append(self.expression(6))
                left = self.modifier(left, name, args)
                continue
            rank = precedence.get(op, -1)
            if rank < minimum:
                break
            self.pop()
            right = self.expression(rank + 1)
            if op in ("and", "&&", "or", "||"):
                left = Expr(
                    f"({left.truth()} {'and' if op in ('and', '&&') else 'or'} {right.truth()})"
                )
            else:
                op = {"eq": "==", "ne": "!=", "gt": ">", "lt": "<", "ge": ">=", "le": "<="}.get(
                    op, op
                )
                left = Expr(f"({left.code} {op} {right.code})")
        return left

    @staticmethod
    def call(name: str, args: list[Expr]) -> Expr:
        if name == "isset" and args:
            return Expr("(" + " and ".join(a.isset() for a in args) + ")")
        if name == "empty" and len(args) == 1:
            return Expr(f"(not {args[0].truth()})")
        if name == "count" and len(args) == 1:
            return Expr(f"({args[0].code}|length)")
        if name == "substr" and len(args) in (2, 3):
            end = f"({args[1].code}+{args[2].code})" if len(args) == 3 else ""
            return Expr(f"({args[0].code})[{args[1].code}:{end}]")
        if name == "is_numeric" and len(args) == 1:
            return Expr(f"(({args[0].code}|float(default=none)) is not none)")
        if name == "range" and len(args) == 2:
            return Expr(f"range({args[0].code},({args[1].code})+1)")
        raise UnsupportedSmarty(f"function {name}")

    @staticmethod
    def modifier(item: Expr, name: str, args: list[Expr]) -> Expr:
        if name == "default" and len(args) == 1:
            return Expr(
                f"({item.code} if {item.isset()} and ({item.code}) != '' else {args[0].code})"
            )
        if name in ("upper", "lower") and not args:
            return Expr(f"({item.code}|{name})")
        if name == "replace" and len(args) == 2:
            return Expr(f"({item.code}|replace({args[0].code},{args[1].code}))")
        if name == "escape" and (not args or args[0].code == '"html"'):
            return Expr(f"({item.code}|e)")
        # truncate has differing Smarty word-boundary semantics. Do not approximate it.
        raise UnsupportedSmarty(f"modifier {name}")


def compile_template(source: str) -> str:
    """Compile a template, rejecting every unrecognised Smarty directive."""
    source = re.sub(r"\{\*.*?\*\}", "", source, flags=re.S)
    # Smarty strips source-line boundaries before substitutions, not whitespace
    # inside variable values. A runtime Jinja trim filter is not equivalent.
    source = re.sub(
        r"\{strip\}(.*?)\{/strip\}",
        lambda m: "".join(line.strip() for line in m[1].splitlines()),
        source,
        flags=re.S,
    )
    literals: dict[str, str] = {}

    def save_literal(m: re.Match) -> str:
        key = f"@@LITERAL{len(literals)}@@"
        literals[key] = m.group(1)
        return key

    source = re.sub(r"\{literal\}(.*?)\{/literal\}", save_literal, source, flags=re.S)
    if "{literal}" in source or "{/literal}" in source:
        raise UnsupportedSmarty("unbalanced literal block")
    assigned = set(re.findall(r"\{\s*\$([A-Za-z_]\w*)\s*=(?!=)", source))
    assigned.update(re.findall(r"\{assign\s+var\s*=\s*['\"]?([A-Za-z_]\w*)", source))
    out = ["{% set __smarty = namespace() %}"] if assigned else []
    stack: list[str] = []
    cursor = 0
    # Braces in dialplans are literal. A Smarty-looking directive must be recognised.
    pattern = re.compile(r"\{(/?[A-Za-z_][^{}]*|\$[^{}]+)\}", re.S)
    for m in pattern.finditer(source):
        out.append(source[cursor : m.start()])
        cursor = m.end()
        tag = m.group(1).strip()
        name, _, body = tag.partition(" ")
        if tag.startswith("$"):
            assign = re.fullmatch(r"\$([A-Za-z_]\w*)\s*=(?!=)\s*(.*)", tag, re.S)
            if assign:
                value = ExpressionParser(assign[2], assigned).parse().code
                out.append(f"{{% set __smarty.{assign[1]} = {value} %}}")
            else:
                out.append("{{ " + ExpressionParser(tag, assigned).parse().output() + " }}")
        elif name in ("if", "elseif"):
            value = ExpressionParser(body, assigned).parse().truth()
            if name == "if":
                stack.append("if")
            elif not stack or stack[-1] != "if":
                raise UnsupportedSmarty("orphan elseif")
            out.append("{% " + ("if" if name == "if" else "elif") + " " + value + " %}")
        elif name == "else":
            if not stack or stack[-1] != "if":
                raise UnsupportedSmarty("orphan else")
            out.append("{% else %}")
        elif name == "foreach":
            loop = re.fullmatch(
                r"(.+?)\s+as\s+(?:\$([A-Za-z_]\w*)\s*=>\s*)?\$([A-Za-z_]\w*)", body, re.S
            )
            if not loop:
                raise UnsupportedSmarty("legacy foreach syntax")
            seq = ExpressionParser(loop[1], assigned).parse().code
            key, value = loop[2], loop[3]
            if key:
                seq = f"({seq}.items() if {seq} is mapping else [])"
                var = f"{key},{value}"
            else:
                seq = f"({seq}.values() if {seq} is mapping else {seq})"
                var = value
            out.append(f"{{% for {var} in {seq} %}}")
            stack.append("foreach")
        elif name == "foreachelse":
            if not stack or stack[-1] != "foreach":
                raise UnsupportedSmarty("orphan foreachelse")
            out.append("{% else %}")
        elif name == "for":
            loop = re.fullmatch(
                r"\$([A-Za-z_]\w*)\s*=\s*(.+?)\s+to\s+(.+?)(?:\s+step\s*=\s*(\d+))?", body, re.S
            )
            if not loop:
                raise UnsupportedSmarty("for syntax")
            start = ExpressionParser(loop[2], assigned).parse().code
            end = ExpressionParser(loop[3], assigned).parse().code
            out.append(f"{{% for {loop[1]} in range({start},({end})+1,{loop[4] or 1}) %}}")
            stack.append("for")
        elif name == "assign":
            assign = re.fullmatch(
                r"var\s*=\s*['\"]?([A-Za-z_]\w*)['\"]?\s+value\s*=\s*(.*)", body, re.S
            )
            if not assign:
                raise UnsupportedSmarty("assign syntax")
            value = ExpressionParser(assign[2], assigned).parse().code
            out.append(f"{{% set __smarty.{assign[1]} = {value} %}}")
        elif name == "strip":
            raise UnsupportedSmarty("nested or unbalanced strip block")
        elif name == "break":
            if not any(s in ("foreach", "for") for s in stack):
                raise UnsupportedSmarty("break outside loop")
            out.append("{% break %}")
        elif name.startswith("/"):
            closing = name[1:]
            if not stack or stack.pop() != closing:
                raise UnsupportedSmarty(f"unbalanced {name}")
            out.append(
                {
                    "if": "{% endif %}",
                    "foreach": "{% endfor %}",
                    "for": "{% endfor %}",
                    "strip": "{% endfilter %}",
                }[closing]
            )
        elif "(" in tag:
            out.append("{{ " + ExpressionParser(tag, assigned).parse().output() + " }}")
        else:
            raise UnsupportedSmarty(f"directive {name}")
    out.append(source[cursor:])
    if stack:
        raise UnsupportedSmarty("unclosed block: " + ",".join(stack))
    result = "".join(out)
    for key, value in literals.items():
        result = result.replace(
            key,
            "{% raw %}"
            + value.replace("{% endraw %}", "{% endraw %}{{ '{% endraw %}' }}{% raw %}")
            + "{% endraw %}",
        )
    return result
