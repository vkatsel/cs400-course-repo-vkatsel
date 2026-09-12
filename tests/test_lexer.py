import unittest
from lexer import lex, Token, CompileError

class TestLexer(unittest.TestCase):
    def test_worked_example(self):
        source = b"i32 mut x{ 10 }\n var t"
        lines = lex(source)
        self.assertEqual(len(lines), 2)
        
        # Line 1 tokens
        l1 = lines[0]
        self.assertEqual(len(l1), 7)
        self.assertEqual(l1[0], Token("keyword", "i32", 1, 1, "typename"))
        self.assertEqual(l1[1], Token("keyword", "mut", 1, 5, "specifier"))
        self.assertEqual(l1[2], Token("identifier", "x", 1, 9))
        self.assertEqual(l1[3], Token("block", "{", 1, 10, "start"))
        self.assertEqual(l1[4], Token("constant", "10", 1, 12, "numeric"))
        self.assertEqual(l1[5], Token("block", "}", 1, 15, "end"))
        self.assertEqual(l1[6], Token("endline", "\n", 1, 16))

        # Line 2 tokens
        l2 = lines[1]
        self.assertEqual(len(l2), 2)
        self.assertEqual(l2[0], Token("identifier", "var", 2, 2))
        self.assertEqual(l2[1], Token("identifier", "t", 2, 6))

    def test_keywords_and_identifiers(self):
        source = b"i32 mut exit my_var total_2 _x"
        lines = lex(source)
        tokens = lines[0]
        self.assertEqual(tokens[0], Token("keyword", "i32", 1, 1, "typename"))
        self.assertEqual(tokens[1], Token("keyword", "mut", 1, 5, "specifier"))
        self.assertEqual(tokens[2], Token("keyword", "exit", 1, 9, "statement"))
        self.assertEqual(tokens[3], Token("identifier", "my_var", 1, 14))
        self.assertEqual(tokens[4], Token("identifier", "total_2", 1, 21))
        self.assertEqual(tokens[5], Token("identifier", "_x", 1, 29))

    def test_numbers_and_operators(self):
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

    def test_unclosed_brace_newline(self):
        source = b"i32 x{ 10\nexit x"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:6: '{' is not closed before the end of the line", str(ctx.exception))

    def test_unclosed_brace_eof(self):
        source = b"i32 x{ 10"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:6: '{' is not closed before the end of the line", str(ctx.exception))

    def test_unexpected_closing_brace(self):
        source = b"i32 x 10}"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:9: unexpected '}'", str(ctx.exception))

    def test_letter_in_number(self):
        source = b"i32 x{10x}"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:9: unexpected character in number: 'x'", str(ctx.exception))

    def test_colon_without_equals(self):
        source = b"x : 5"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:3: unexpected byte ':'", str(ctx.exception))

    def test_unexpected_byte(self):
        source = b"i32 x{$}"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:7: unexpected byte '$'", str(ctx.exception))

    def test_non_ascii_byte(self):
        source = b"i32 x{\xff}"
        with self.assertRaises(CompileError) as ctx:
            lex(source)
        self.assertIn("line 1:7: unexpected byte '\\xff'", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
