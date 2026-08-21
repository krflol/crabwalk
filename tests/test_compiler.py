import pytest
import subprocess
import os
import glob
import sys

def test_compile_fail():
    compile_fail_dir = os.path.join(os.path.dirname(__file__), "compile_fail")
    for test_file in glob.glob(os.path.join(compile_fail_dir, "*.py")):
        print(f"Testing compile fail: {test_file}")
        result = subprocess.run([sys.executable, test_file], capture_output=True, text=True)
        # It must fail
        assert result.returncode != 0, f"{test_file} compiled successfully but was expected to fail"
        # Optional: check if output contains "error" or "Crabwalk: Unsupported"
        assert "error" in result.stderr.lower() or "crabwalk" in result.stderr.lower() or "error" in result.stdout.lower() or "crabwalk" in result.stdout.lower(), f"Unexpected error output in {test_file}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
