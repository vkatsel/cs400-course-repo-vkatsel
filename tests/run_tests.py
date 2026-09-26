import os
import sys
import subprocess
import shutil
import tempfile
from pathlib import Path

for _p in (
    "/home/ubuntu/lcd/lib/python3.12/site-packages",
    str(Path.home() / "lcd/lib/python3.12/site-packages"),
):
    if _p not in sys.path and Path(_p).exists():
        sys.path.insert(0, _p)

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
            subprocess.run(["llc", "-filetype=obj", "-relocation-model=pic", str(out_ll), "-o", str(out_o)], check=True)
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

def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    compiler_py = repo_root / "compiler.py"
    tests_dir = repo_root / "tests"

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

    passed = 0
    failed = 0

    print(f"Running {len(test_files)} tests...\n")

    py_exe = get_python_exe()

    with tempfile.TemporaryDirectory() as tmpdir:
        for test_file in test_files:
            test_name = test_file.stem
            is_fail_test = test_name.startswith("fail") or test_file.parent.name == "err"
            out_ll = Path(tmpdir) / f"{test_name}.ll"
            expected_file = test_file.with_suffix(".expected")
            ast_file = test_file.with_suffix(".ast")

            expected_text = expected_file.read_text(encoding="utf-8").strip() if expected_file.exists() else None

            # For valid tests, verify AST matches .ast file if present
            if not is_fail_test and ast_file.exists():
                ast_res = subprocess.run(
                    [py_exe, str(compiler_py), "--ast", str(test_file)],
                    capture_output=True,
                    text=True,
                )
                if ast_res.returncode != 0:
                    print(f"❌ FAIL: {test_name} (--ast execution error)")
                    print(f"   stderr: {ast_res.stderr.strip()}")
                    failed += 1
                    continue
                expected_ast = ast_file.read_text(encoding="utf-8").strip()
                if ast_res.stdout.strip() != expected_ast:
                    print(f"❌ FAIL: {test_name} (AST mismatch)")
                    print(f"   Expected AST:\n{expected_ast}")
                    print(f"   Actual AST:\n{ast_res.stdout.strip()}")
                    failed += 1
                    continue

            res = subprocess.run(
                [py_exe, str(compiler_py), str(test_file), str(out_ll)],
                capture_output=True,
                text=True,
            )

            if is_fail_test:
                if res.returncode == 0:
                    print(f"❌ FAIL: {test_name} (expected failure, but exited with 0)")
                    failed += 1
                    continue
                stderr_out = res.stderr.strip()
                if expected_text and expected_text not in stderr_out:
                    print(f"❌ FAIL: {test_name}")
                    print(f"   Expected stderr: {expected_text}")
                    print(f"   Actual stderr:   {stderr_out}")
                    failed += 1
                    continue
                print(f"✅ PASS: {test_name} -> {stderr_out}")
                passed += 1
            else:
                if res.returncode != 0:
                    print(f"❌ FAIL: {test_name} (compilation error)")
                    print(f"   stderr: {res.stderr.strip()}")
                    failed += 1
                    continue

                if not out_ll.exists() or out_ll.stat().st_size == 0:
                    print(f"❌ FAIL: {test_name} (no IR output generated)")
                    failed += 1
                    continue

                actual_output = run_ir(out_ll)
                if actual_output is not None and expected_text:
                    if actual_output != expected_text:
                        print(f"❌ FAIL: {test_name}")
                        print(f"   Expected output: {expected_text}")
                        print(f"   Actual output:   {actual_output}")
                        failed += 1
                        continue

                ast_info = " + AST" if ast_file.exists() else ""
                output_info = f" (output: '{actual_output}'{ast_info})" if actual_output is not None else f" (IR generated{ast_info})"
                print(f"✅ PASS: {test_name}{output_info}")
                passed += 1

    print(f"\nResult: {passed} passed, {failed} failed.")
    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
