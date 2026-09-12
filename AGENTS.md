# Agent Guidelines & Project Rules

## Python 3.12+ Coding Standards
When writing or modifying Python code in this workspace, strictly follow modern Python 3.12+ conventions:

1. **Modern Type Annotations**:
   - Do NOT import `List`, `Dict`, `Tuple`, `Set`, `Optional`, or `Union` from `typing`.
   - Use built-in generics directly: `list[...]`, `dict[...]`, `tuple[...]`, `set[...]`.
   - Use union operator `X | Y` instead of `Optional[X]` or `Union[X, Y]`.
   - Use `type` aliases (`type Name = ...`) if defining type aliases.

2. **Structural Pattern Matching**:
   - Prefer `match ... case ...` statements for state machines, AST traversal, token evaluation, and complex branching.

3. **Data Classes & Enums**:
   - Prefer `@dataclass(slots=True)` (or `frozen=True`) for records and data containers (e.g., `Token`, AST nodes).
   - Use `enum.StrEnum` for string-based state and token kind constants.

4. **Modern Syntax & Features**:
   - Leverage Python 3.12 f-string capabilities (nested quotes, backslashes inside expressions).
   - Keep code idiomatic, clean, modular, and fully typed.
