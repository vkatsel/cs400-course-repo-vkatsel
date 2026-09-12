import os
import sys
import subprocess
import shutil
import tempfile
from pathlib import Path


def main():
    repo_root = Path(__file__).resolve().parent.parent
    compiler_py = repo_root / "compiler.py"
    tests_dir = repo_root / "tests"

    if not compiler_py.exists():
        print(f"Error: compiler.py not found at {compiler_py}", file=sys.stderr)
        sys.exit(1)

    has_lli = shutil.which("lli") is not None
    has_llc = shutil.which("llc") is not None and shutil.which("clang") is not None

    test_files = sorted(
        list(tests_dir.glob("test*.txt")) + list(tests_dir.glob("fail*.txt"))
    )
    if not test_files:
        print("No test files found.")
        sys.exit(1)

    passed = 0
    failed = 0

    print(f"Running {len(test_files)} tests...\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        for test_file in test_files:
            test_name = test_file.stem
            is_fail_test = test_name.startswith("fail")
            out_ll = Path(tmpdir) / f"{test_name}.ll"
            expected_file = tests_dir / f"{test_name}.expected"

            expected_text = (
                expected_file.read_text().strip() if expected_file.exists() else None
            )

            # Run compiler
            res = subprocess.run(
                [sys.executable, str(compiler_py), str(test_file), str(out_ll)],
                capture_output=True,
                text=True,
            )

            if is_fail_test:
                if res.returncode == 0:
                    print(
                        f"❌ FAIL: {test_name} (expected compilation failure, but exited with 0)"
                    )
                    failed += 1
                    continue
                stderr_out = res.stderr.strip()
                if expected_text and expected_text not in stderr_out:
                    print(f"❌ FAIL: {test_name}")
                    print(f"   Expected stderr to contain: {expected_text}")
                    print(f"   Actual stderr: {stderr_out}")
                    failed += 1
                    continue
                print(f"✅ PASS: {test_name} (failed as expected: {stderr_out})")
                passed += 1
            else:
                if res.returncode != 0:
                    print(
                        f"❌ FAIL: {test_name} (compilation failed with code {res.returncode})"
                    )
                    print(f"   stderr: {res.stderr.strip()}")
                    failed += 1
                    continue

                if not out_ll.exists() or out_ll.stat().st_size == 0:
                    print(f"❌ FAIL: {test_name} (no IR output generated)")
                    failed += 1
                    continue

                # Run executable if runtime is available
                run_output = None
                if has_lli:
                    lli_res = subprocess.run(
                        ["lli", str(out_ll)], capture_output=True, text=True
                    )
                    run_output = lli_res.stdout.strip()
                elif has_llc:
                    out_o = Path(tmpdir) / f"{test_name}.o"
                    out_bin = Path(tmpdir) / f"{test_name}.bin"
                    subprocess.run(
                        [
                            "llc",
                            "-filetype=obj",
                            "-relocation-model=pic",
                            str(out_ll),
                            "-o",
                            str(out_o),
                        ],
                        check=True,
                    )
                    subprocess.run(
                        ["clang", "-fPIE", str(out_o), "-o", str(out_bin)], check=True
                    )
                    bin_res = subprocess.run(
                        [str(out_bin)], capture_output=True, text=True
                    )
                    run_output = bin_res.stdout.strip()

                if run_output is not None and expected_text:
                    if run_output != expected_text:
                        print(f"❌ FAIL: {test_name}")
                        print(f"   Expected output: {expected_text}")
                        print(f"   Actual output:   {run_output}")
                        failed += 1
                        continue

                status_extra = (
                    f" (output: {run_output})"
                    if run_output is not None
                    else " (IR generated)"
                )
                print(f"✅ PASS: {test_name}{status_extra}")
                passed += 1

    print(f"\nResult: {passed} passed, {failed} failed.")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
