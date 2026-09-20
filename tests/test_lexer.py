import unittest
from lexer import lex, Token, CompileError

class TestLexer(unittest.TestCase):
    def test_worked_example(self) -> None:
        source = b"i32 mut x{ 10 }\n var t"
        lines = lex(source)
        self.assertEqual(len(lines), 2)

        # Line 1 tokens
        l1 = lines[0]
        self.assertEqual(len(l1), 7)
        self.assertEqual(l1[0], Token("keyword", "i32", 1, 1, "typename"))
        self.assertTrue(l1[0].is_keyword)
        self.assertEqual(l1[1], Token("keyword", "mut", 1, 5, "specifier"))
        self.assertEqual(l1[2], Token("identifier", "x", 1, 9))
        self.assertTrue(l1[2].is_identifier)
        self.assertEqual(l1[3], Token("block", "{", 1, 10, "start"))
        self.assertTrue(l1[3].is_block)
        self.assertEqual(l1[4], Token("constant", "10", 1, 12, "numeric"))
        self.assertTrue(l1[4].is_number)
        self.assertEqual(l1[5], Token("block", "}", 1, 15, "end"))
        self.assertEqual(l1[6], Token("endline", "\n", 1, 16))
        self.assertTrue(l1[6].is_endline)

        # Line 2 tokens
        l2 = lines[1]
        self.assertEqual(len(l2), 2)
        self.assertEqual(l2[0], Token("identifier", "var", 2, 2))
        self.assertEqual(l2[1], Token("identifier", "t", 2, 6))

    def test_crlf_line_endings(self) -> None:
        source = b"i32 x{1}\r\nexit x\r\n"
        lines = lex(source)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0][0], Token("keyword", "i32", 1, 1, "typename"))
        self.assertEqual(lines[1][0], Token("keyword", "exit", 2, 1, "statement"))

    def test_keywords_and_identifiers(self) -> None:
        source = b"i32 mut exit my_var total_2 _x"
        lines = lex(source)
        tokens = lines[0]
        self.assertEqual(tokens[0], Token("keyword", "i32", 1, 1, "typename"))
        self.assertEqual(tokens[1], Token("keyword", "mut", 1, 5, "specifier"))
        self.assertEqual(tokens[2], Token("keyword", "exit", 1, 9, "statement"))
        self.assertEqual(tokens[3], Token("identifier", "my_var", 1, 14))
        self.assertEqual(tokens[4], Token("identifier", "total_2", 1, 21))
        self.assertEqual(tokens[5], Token("identifier", "_x", 1, 29))

    def test_numbers_and_operators(self) -> None:
        source = b"x := y + 10 - 2 * 3"
        lines = lex(source)
        tokens = lines[0]
        kinds = [(t.kind, t.text) for t in tokens]
        expected = [
            ("identifier", "x"),
            ("operator", ":="),
            ("identifier", "y"),
            ("operator", "+"),
            ("constant", "10"),
            ("operator", "-"),
            ("constant", "2"),
            ("operator", "*"),
            ("constant", "3"),
        ]
        self.assertEqual(kinds, expected)
        self.assertTrue(tokens[1].is_operator)

    def test_unclosed_brace_newline(self) -> None:
        source = b"i32 x{ 10\nexit x"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:6: '{' is not closed before the end of the line", str(ctx.exception))

    def test_unclosed_brace_eof(self) -> None:
        source = b"i32 x{ 10"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:6: '{' is not closed before the end of the line", str(ctx.exception))

    def test_unexpected_closing_brace(self) -> None:
        source = b"i32 x 10}"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:9: unexpected '}'", str(ctx.exception))

    def test_nested_brace_error(self) -> None:
        source = b"i32 x{{10}}"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:7: nested '{' is not allowed", str(ctx.exception))

    def test_letter_in_number(self) -> None:
        source = b"i32 x{10x}"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:9: unexpected character in number: 'x'", str(ctx.exception))

    def test_colon_without_equals(self) -> None:
        source = b"x : 5"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:3: unexpected byte ':'", str(ctx.exception))

    def test_unexpected_byte(self) -> None:
        source = b"i32 x{$}"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:7: unexpected byte '$'", str(ctx.exception))

    def test_non_ascii_byte(self) -> None:
        source = b"i32 x{\xff}"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:7: unexpected byte '\\xff'", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
