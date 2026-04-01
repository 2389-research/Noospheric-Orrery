"""Quick smoke test: verify claude-agent-sdk and its bundled CLI work."""
import subprocess
import sys

print("=== Test 1: Import claude-agent-sdk ===")
try:
    from claude_agent_sdk import AgentClient
    print("OK: claude-agent-sdk imports successfully")
except ImportError as e:
    print(f"FAIL: {e}")
    sys.exit(1)

print("\n=== Test 2: Import simmer-sdk ===")
try:
    from simmer_sdk import refine
    print("OK: simmer-sdk imports successfully")
except ImportError as e:
    print(f"FAIL: {e}")
    sys.exit(1)

print("\n=== Test 3: Find bundled Claude CLI ===")
try:
    # The SDK bundles the CLI - find it
    import claude_agent_sdk
    import os
    sdk_dir = os.path.dirname(claude_agent_sdk.__file__)
    print(f"SDK location: {sdk_dir}")

    # List contents to find the binary
    for root, dirs, files in os.walk(sdk_dir):
        for f in files:
            path = os.path.join(root, f)
            if 'claude' in f.lower() or os.access(path, os.X_OK):
                print(f"  Found: {path}")
except Exception as e:
    print(f"WARN: Could not inspect SDK dir: {e}")

print("\n=== Test 4: Try running claude --version ===")
try:
    result = subprocess.run(
        ["claude", "--version"],
        capture_output=True, text=True, timeout=30,
        env={**dict(__import__('os').environ), "CLAUDECODE": ""}
    )
    print(f"stdout: {result.stdout.strip()}")
    print(f"stderr: {result.stderr.strip()}")
    print(f"returncode: {result.returncode}")
    if result.returncode == 0:
        print("OK: Claude CLI works!")
    else:
        print("WARN: Non-zero exit code, but CLI was found")
except FileNotFoundError:
    print("FAIL: claude not on PATH")
    # Try to find it via python -m
    print("Trying: python -m claude_agent_sdk ...")
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import claude_agent_sdk; print(claude_agent_sdk.__file__)"],
            capture_output=True, text=True
        )
        print(f"SDK at: {result.stdout.strip()}")
    except Exception as e2:
        print(f"Also failed: {e2}")
except subprocess.TimeoutExpired:
    print("WARN: claude --version timed out (may be trying interactive prompt)")
except Exception as e:
    print(f"FAIL: {e}")

print("\n=== Done ===")
