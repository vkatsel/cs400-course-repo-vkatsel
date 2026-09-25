import sys
from dataclasses import dataclass
from enum import StrEnum


class CompileError(Exception):
    def __init__(self, line: int, col: int, msg: str) -> None:
        self.line = line
        self.col = col
        self.msg = msg
        super().__init__(f"compilation error: line {line}:{col}: {msg}")


@dataclass(slots=True, frozen=True)
class Token:
    kind: str
    text: str
    line: int
    col: int
    subkind: str | None = None

    def __repr__(self) -> str:
        loc = f"{self.line}:{self.col}"
        match self.kind:
            case "endline":
                return rf"(\n, endline, {loc})"
            case _ if self.subkind is not None:
                return f"({self.text}, {self.kind}, {self.subkind}, {loc})"
            case _:
                return f"({self.text}, {self.kind}, {loc})"

    @property
    def is_keyword(self) -> bool:
        return self.kind == "keyword"

    @property
    def is_identifier(self) -> bool:
        return self.kind == "identifier"

    @property
    def is_number(self) -> bool:
        return self.kind == "constant" and self.subkind == "numeric"

    @property
    def is_operator(self) -> bool:
        return self.kind == "operator"

    @property
    def is_block(self) -> bool:
        return self.kind == "block"

    @property
    def is_endline(self) -> bool:
        return self.kind == "endline"


class State(StrEnum):
    START = "START"
    IDENT = "IDENT"
    NUMBER = "NUMBER"
    COLON = "COLON"


KEYWORDS: dict[str, tuple[str, str]] = {
    "i32": ("keyword", "typename"),
    "mut": ("keyword", "specifier"),
    "exit": ("keyword", "statement"),
}


def is_alpha(b: int | None) -> bool:
    if b is None:
        return False
    return (65 <= b <= 90) or (97 <= b <= 122) or (b == 95)  # 'A'-'Z', 'a'-'z', '_'


def is_digit(b: int | None) -> bool:
    if b is None:
        return False
    return 48 <= b <= 57  # '0'-'9'


def lex(data: bytes) -> list[list[Token]]:
    lines: list[list[Token]] = []
    tokens: list[Token] = []

    state = State.START
    line, col = 1, 1
    start_idx, start_line, start_col = 0, 1, 1

    open_brace_loc: tuple[int, int] | None = None
    i = 0
    n = len(data)

    while i <= n:
        b = data[i] if i < n else None

        if b is not None and b > 127:
            raise CompileError(line, col, f"unexpected byte '\\x{b:02x}'")

        match state:
            case State.START:
                match b:
                    case None:
                        if open_brace_loc is not None:
                            raise CompileError(
                                open_brace_loc[0],
                                open_brace_loc[1],
                                "'{' is not closed before the end of the line",
                            )
                        break
                    case 32 | 9:  # ' ' (space), '\t' (tab)
                        i += 1
                        col += 1
                    case 13:  # '\r' (CRLF carriage return)
                        i += 1
                        if i < n and data[i] == 10:
                            pass
                    case 10:  # '\n' (newline / end of line)
                        if open_brace_loc is not None:
                            raise CompileError(
                                open_brace_loc[0],
                                open_brace_loc[1],
                                "'{' is not closed before the end of the line",
                            )
                        tokens.append(Token("endline", "\n", line, col))
                        lines.append(tokens)
                        tokens = []
                        line += 1
                        col = 1
                        i += 1
                    case _ if is_alpha(b):
                        state = State.IDENT
                        start_idx, start_line, start_col = i, line, col
                        i += 1
                        col += 1
                    case _ if is_digit(b):
                        state = State.NUMBER
                        start_idx, start_line, start_col = i, line, col
                        i += 1
                        col += 1
                    case 123:  # '{' (block start)
                        if open_brace_loc is not None:
                            raise CompileError(line, col, "nested '{' is not allowed")
                        open_brace_loc = (line, col)
                        tokens.append(Token("block", "{", line, col, "start"))
                        i += 1
                        col += 1
                    case 125:  # '}' (block end)
                        if open_brace_loc is None:
                            raise CompileError(line, col, "unexpected '}'")
                        open_brace_loc = None
                        tokens.append(Token("block", "}", line, col, "end"))
                        i += 1
                        col += 1
                    case 58:  # ':' (start of ':=')
                        state = State.COLON
                        start_line, start_col = line, col
                        i += 1
                        col += 1
                    case 43 | 45 | 42:  # '+', '-', '*' (operators)
                        tokens.append(Token("operator", chr(b), line, col))
                        i += 1
                        col += 1
                    case _:
                        char_str = chr(b)
                        raise CompileError(line, col, f"unexpected byte '{char_str}'")

            case State.IDENT:
                if b is not None and (is_alpha(b) or is_digit(b)):
                    i += 1
                    col += 1
                else:
                    word = data[start_idx:i].decode("ascii")
                    if word in KEYWORDS:
                        kind, subkind = KEYWORDS[word]
                        tokens.append(Token(kind, word, start_line, start_col, subkind))
                    else:
                        tokens.append(Token("identifier", word, start_line, start_col))
                    state = State.START
                    continue

            case State.NUMBER:
                if b is not None and is_digit(b):
                    i += 1
                    col += 1
                elif b is not None and is_alpha(b):
                    raise CompileError(
                        line, col, f"unexpected character in number: '{chr(b)}'"
                    )
                else:
                    num_str = data[start_idx:i].decode("ascii")
                    tokens.append(
                        Token("constant", num_str, start_line, start_col, "numeric")
                    )
                    state = State.START
                    continue

            case State.COLON:
                if b == ord("="):
                    tokens.append(Token("operator", ":=", start_line, start_col))
                    state = State.START
                    i += 1
                    col += 1
                else:
                    raise CompileError(start_line, start_col, "unexpected byte ':'")

    if tokens:
        lines.append(tokens)

    return lines


def print_tokens(lines: list[list[Token]]) -> None:
    for line_tokens in lines:
        print(" ".join(str(tok) for tok in line_tokens))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 lexer.py <source_file>", file=sys.stderr)
        sys.exit(1)

    filename = sys.argv[1]
    try:
        with open(filename, "rb") as f:
            content = f.read()
        token_lines = lex(content)
        print_tokens(token_lines)
    except CompileError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: file '{filename}' not found", file=sys.stderr)
        sys.exit(1)
