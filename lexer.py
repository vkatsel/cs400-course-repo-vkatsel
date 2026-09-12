import sys
from typing import List, Optional, Tuple

class CompileError(Exception):
    def __init__(self, line: int, col: int, msg: str):
        self.line = line
        self.col = col
        self.msg = msg
        super().__init__(f"compilation error: line {line}:{col}: {msg}")

class Token:
    def __init__(self, kind: str, text: str, line: int, col: int, subkind: Optional[str] = None):
        self.kind = kind          # keyword, identifier, constant, block, operator, endline
        self.text = text
        self.line = line          # 1-based
        self.col = col            # 1-based (start column of token)
        self.subkind = subkind    # typename, specifier, statement, numeric, start, end

    def __repr__(self) -> str:
        if self.kind == "endline":
            return r"(\n, endline)"
        if self.subkind:
            return f"({self.text}, {self.kind}, {self.subkind})"
        return f"({self.text}, {self.kind})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Token):
            return False
        return (self.kind, self.text, self.line, self.col, self.subkind) == \
               (other.kind, other.text, other.line, other.col, other.subkind)

KEYWORDS = {
    "i32": ("keyword", "typename"),
    "mut": ("keyword", "specifier"),
    "exit": ("keyword", "statement"),
}

def is_alpha(b: Optional[int]) -> bool:
    if b is None:
        return False
    return (65 <= b <= 90) or (97 <= b <= 122) or (b == 95)  # A-Z, a-z, _

def is_digit(b: Optional[int]) -> bool:
    if b is None:
        return False
    return 48 <= b <= 57  # 0-9

def lex(data: bytes) -> List[List[Token]]:
    lines: List[List[Token]] = []
    tokens: List[Token] = []

    state = "START"
    line, col = 1, 1
    start_idx, start_col = 0, 1

    open_brace_loc: Optional[Tuple[int, int]] = None
    i = 0
    n = len(data)

    while i <= n:
        b = data[i] if i < n else None

        # Check ASCII validity
        if b is not None and b > 127:
            raise CompileError(line, col, f"unexpected byte '\\x{b:02x}'")

        if state == "START":
            if b is None:
                if open_brace_loc is not None:
                    raise CompileError(open_brace_loc[0], open_brace_loc[1], "'{' is not closed before the end of the line")
                break
            elif b in (32, 9):  # space, tab
                i += 1
                col += 1
            elif b == 10:  # newline '\n'
                if open_brace_loc is not None:
                    raise CompileError(open_brace_loc[0], open_brace_loc[1], "'{' is not closed before the end of the line")
                tokens.append(Token("endline", "\n", line, col))
                lines.append(tokens)
                tokens = []
                line += 1
                col = 1
                i += 1
            elif b == 13:  # carriage return '\r' (skip if followed by \n)
                i += 1
            elif is_alpha(b):
                state = "IDENT"
                start_idx = i
                start_col = col
                i += 1
                col += 1
            elif is_digit(b):
                state = "NUMBER"
                start_idx = i
                start_col = col
                i += 1
                col += 1
            elif b == ord("{"):
                if open_brace_loc is not None:
                    raise CompileError(line, col, "nested '{' is not allowed")
                open_brace_loc = (line, col)
                tokens.append(Token("block", "{", line, col, "start"))
                i += 1
                col += 1
            elif b == ord("}"):
                if open_brace_loc is None:
                    raise CompileError(line, col, "unexpected '}'")
                open_brace_loc = None
                tokens.append(Token("block", "}", line, col, "end"))
                i += 1
                col += 1
            elif b == ord(":"):
                state = "COLON"
                start_col = col
                i += 1
                col += 1
            elif b in (ord("+"), ord("-"), ord("*")):
                tokens.append(Token("operator", chr(b), line, col))
                i += 1
                col += 1
            else:
                char_str = chr(b)
                raise CompileError(line, col, f"unexpected byte '{char_str}'")

        elif state == "IDENT":
            if b is not None and (is_alpha(b) or is_digit(b)):
                i += 1
                col += 1
            else:
                word = data[start_idx:i].decode("ascii")
                if word in KEYWORDS:
                    kind, subkind = KEYWORDS[word]
                    tokens.append(Token(kind, word, line, start_col, subkind))
                else:
                    tokens.append(Token("identifier", word, line, start_col))
                state = "START"
                # Do NOT advance i or col; re-examine byte in START state
                continue

        elif state == "NUMBER":
            if b is not None and is_digit(b):
                i += 1
                col += 1
            elif b is not None and is_alpha(b):
                raise CompileError(line, col, f"unexpected character in number: '{chr(b)}'")
            else:
                num_str = data[start_idx:i].decode("ascii")
                tokens.append(Token("constant", num_str, line, start_col, "numeric"))
                state = "START"
                # Do NOT advance i or col; re-examine byte in START state
                continue

        elif state == "COLON":
            if b == ord("="):
                tokens.append(Token("operator", ":=", line, start_col))
                state = "START"
                i += 1
                col += 1
            else:
                raise CompileError(line, start_col, "unexpected byte ':'")

    if tokens:
        lines.append(tokens)

    return lines

def print_tokens(lines: List[List[Token]]) -> None:
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
