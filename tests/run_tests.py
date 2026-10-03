import os
import sys
import subprocess
import shutil
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

for _p in (
    "/home/ubuntu/lcd/lib/python3.12/site-packages",
    str(Path.home() / "lcd/lib/python3.12/site-packages"),
):
    if _p not in sys.path and Path(_p).exists():
        sys.path.insert(0, _p)

from compiler import parse_ast, compile_source, CompileError


def get_python_exe() -> str:
    return sys.executable


def run_ir(out_ll: Path) -> str | None:
    if shutil.which("lli") is not None:
        res = subprocess.run(["lli", str(out_ll)], capture_output=True, text=True)
        return res.stdout.strip()

    if shutil.which("llc") is not None and shutil.which("clang") is not None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_o = Path(tmpdir) / "out.o"
            out_bin = Path(tmpdir) / "out.bin"
            subprocess.run(
                ["llc", "-filetype=obj", "-relocation-model=pic", str(out_ll), "-o", str(out_o)],
                check=True,
            )
            subprocess.run(["clang", "-fPIE", str(out_o), "-o", str(out_bin)], check=True)
            bin_res = subprocess.run([str(out_bin)], capture_output=True, text=True)
            return bin_res.stdout.strip()

    jit_script = f"""
import sys
from pathlib import Path
for _p in ('/home/ubuntu/lcd/lib/python3.12/site-packages', str(Path.home() / 'lcd/lib/python3.12/site-packages')):
    if _p not in sys.path and Path(_p).exists():
        sys.path.insert(0, _p)

import llvmlite.binding as llvm
import ctypes

llvm.initialize_native_target()
llvm.initialize_native_asmprinter()

with open(r'{out_ll}', 'r', encoding='utf-8') as f:
    ll_text = f.read()

llvm_mod = llvm.parse_assembly(ll_text)
target_machine = llvm.Target.from_default_triple().create_target_machine()
engine = llvm.create_mcjit_compiler(llvm_mod, target_machine)
engine.finalize_object()
func_ptr = engine.get_function_address('main')
cfunc = ctypes.CFUNCTYPE(ctypes.c_int32)(func_ptr)
cfunc()
"""
    py_exe = get_python_exe()
    res = subprocess.run([py_exe, "-c", jit_script], capture_output=True, text=True)
    if res.returncode == 0:
        return res.stdout.strip()
    return None


def run_single_test(test_file: Path, tmpdir: str) -> tuple[bool, str]:
    test_name = test_file.stem
    is_fail_test = test_name.startswith("fail") or test_file.parent.name == "err"
    expected_file = test_file.with_suffix(".expected")
    ast_file = test_file.with_suffix(".ast")
    expected_text = (
        expected_file.read_text(encoding="utf-8").strip()
        if expected_file.exists()
        else None
    )

    try:
        content = test_file.read_bytes()
    except Exception as e:
        return False, f"❌ FAIL: {test_name} (unable to read file: {e})"

    if is_fail_test:
        try:
            compile_source(content)
            return False, f"❌ FAIL: {test_name} (expected failure, but exited with 0)"
        except CompileError as e:
            stderr_out = str(e)
            if expected_text and expected_text not in stderr_out:
                msg = (
                    f"❌ FAIL: {test_name}\n"
                    f"   Expected stderr: {expected_text}\n"
                    f"   Actual stderr:   {stderr_out}"
                )
                return False, msg
            return True, f"✅ PASS: {test_name} -> {stderr_out}"
        except Exception as e:
            return False, f"❌ FAIL: {test_name} (unexpected crash: {e})"
    else:
        if ast_file.exists():
            try:
                ast = parse_ast(content)
                expected_ast = ast_file.read_text(encoding="utf-8").strip()
                actual_ast = ast.dump().strip()
                if actual_ast != expected_ast:
                    msg = (
                        f"❌ FAIL: {test_name} (AST mismatch)\n"
                        f"   Expected AST:\n{expected_ast}\n"
                        f"   Actual AST:\n{actual_ast}"
                    )
                    return False, msg
            except Exception as e:
                return False, f"❌ FAIL: {test_name} (--ast execution error: {e})"

        try:
            mod = compile_source(content)
        except CompileError as e:
            return False, f"❌ FAIL: {test_name} (compilation error: {e})"
        except Exception as e:
            return False, f"❌ FAIL: {test_name} (compiler crash: {e})"

        out_ll = Path(tmpdir) / f"{test_name}.ll"
        out_ll.write_text(str(mod), encoding="utf-8")

        if not out_ll.exists() or out_ll.stat().st_size == 0:
            return False, f"❌ FAIL: {test_name} (no IR output generated)"

        actual_output = run_ir(out_ll)
        if actual_output is not None and expected_text:
            if actual_output != expected_text:
                msg = (
                    f"❌ FAIL: {test_name}\n"
                    f"   Expected output: {expected_text}\n"
                    f"   Actual output:   {actual_output}"
                )
                return False, msg

        ast_info = " + AST" if ast_file.exists() else ""
        output_info = (
            f" (output: '{actual_output}'{ast_info})"
            if actual_output is not None
            else f" (IR generated{ast_info})"
        )
        return True, f"✅ PASS: {test_name}{output_info}"


def main() -> None:
    compiler_py = REPO_ROOT / "compiler.py"
    tests_dir = REPO_ROOT / "tests"

    if not compiler_py.exists():
        print(f"Error: compiler.py not found at {compiler_py}", file=sys.stderr)
        sys.exit(1)

    test_files = sorted(
        list(tests_dir.glob("test*.txt"))
        + list(tests_dir.glob("fail*.txt"))
        + list((tests_dir / "ok").glob("*.txt"))
        + list((tests_dir / "err").glob("*.txt"))
    )
    if not test_files:
        print("No test files found.")
        sys.exit(1)

    print(f"Running {len(test_files)} tests...\n")

    workers = min(8, (os.cpu_count() or 2) * 2)
    passed = 0
    failed = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for ok, msg in executor.map(lambda tf: run_single_test(tf, tmpdir), test_files):
                print(msg)
                if ok:
                    passed += 1
                else:
                    failed += 1

    print(f"\nResult: {passed} passed, {failed} failed.")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
