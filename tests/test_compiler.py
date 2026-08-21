import pytest
import subprocess
import os
import glob
import sys
import re

def test_compile_fail():
    compile_fail_dir = os.path.join(os.path.dirname(__file__), "compile_fail")
    for test_file in glob.glob(os.path.join(compile_fail_dir, "*.py")):
        print(f"Testing compile fail: {test_file}")
        
        expected_rustc = None
        expected_crabwalk = None
        
        with open(test_file, "r") as f:
            content = f.read()
            rustc_match = re.search(r"# expected-rustc:\s*([^\n]+)", content)
            crabwalk_match = re.search(r"# expected-crabwalk:\s*([^\n]+)", content)
            if rustc_match:
                expected_rustc = rustc_match.group(1).strip()
            if crabwalk_match:
                expected_crabwalk = crabwalk_match.group(1).strip()
                
        result = subprocess.run([sys.executable, test_file], capture_output=True, text=True)
        
        # It must fail
        assert result.returncode != 0, f"{test_file} compiled successfully but was expected to fail"
        
        output = (result.stdout + result.stderr)
        
        if expected_rustc:
            assert expected_rustc in output, f"Expected rustc error {expected_rustc} not found in output:\n{output}"
        elif expected_crabwalk:
            assert expected_crabwalk in output, f"Expected crabwalk error {expected_crabwalk} not found in output:\n{output}"
        else:
            # Fallback for undocumented tests
            assert "error" in output.lower() or "crabwalk" in output.lower(), f"Unexpected error output in {test_file}\n{output}"
