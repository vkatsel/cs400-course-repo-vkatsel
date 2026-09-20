import os
import sys
import subprocess
import shutil
import tempfile
from pathlib import Path

def get_python_exe() -> str:
    try:
        import llvmlite  # noqa: F401
        return sys.executable
    except ImportError:
        for candidate in ("/home/ubuntu/lcd/bin/python", str(Path.home() / "lcd/bin/python")):
            if Path(candidate).exists():
                return candidate
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

    test_files = sorted(list(tests_dir.glob("test*.txt")) + list(tests_dir.glob("fail*.txt")))
    if not test_files:
        print("No test files found.")
        sys.exit(1)

    passed = 0
    failed = 0

    print(f"Running {len(test_files)} tests...\n")

    py_exe = get_python_exe()

    # Step 0: Test --ast flag
    ast_res = subprocess.run(
        [py_exe, str(compiler_py), "--ast", str(tests_dir / "test1_valid_spec.txt")],
        capture_output=True,
        text=True,
    )
    expected_ast = """Program
  Decl x const
    Const 0
  Decl y mut
    Const 10
  Decl z const
    BinOp +
      Const 2
      Const 5
  Decl t mut
    BinOp +
      Var x
      Const 10
  Assign t
    BinOp *
      Var t
      Var z
  Exit
    Var t"""
    if ast_res.returncode == 0 and ast_res.stdout.strip() == expected_ast.strip():
        print("✅ PASS: compiler --ast on test1_valid_spec\n")
    else:
        print("❌ FAIL: compiler --ast on test1_valid_spec")
        print(f"   stdout: {ast_res.stdout.strip()}")
        print(f"   stderr: {ast_res.stderr.strip()}")
        failed += 1

    with tempfile.TemporaryDirectory() as tmpdir:
        for test_file in test_files:
            test_name = test_file.stem
            is_fail_test = test_name.startswith("fail")
            out_ll = Path(tmpdir) / f"{test_name}.ll"
            expected_file = tests_dir / f"{test_name}.expected"

            expected_text = expected_file.read_text(encoding="utf-8").strip() if expected_file.exists() else None

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

                output_info = f" (output: '{actual_output}')" if actual_output is not None else " (IR generated)"
                print(f"✅ PASS: {test_name}{output_info}")
                passed += 1

    print(f"\nResult: {passed} passed, {failed} failed.")
    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
