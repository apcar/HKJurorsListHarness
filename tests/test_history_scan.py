"""Check committed and deleted content, not just the working tree."""
import subprocess
from jurors_harness.secret_scan import scan_history


def test_deleted_secret_is_found_in_history_without_echoing_value(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    git("init")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    secret = "sk-" + "or-" + "synthetic-not-a-real-credential"
    file = tmp_path / "removed.txt"
    file.write_text(secret)
    git("add", "removed.txt")
    git("commit", "-m", "fixture")
    file.unlink()
    git("add", "-u")
    git("commit", "-m", "remove fixture")
    findings = scan_history(tmp_path)
    assert findings
    assert all(secret not in str(f) for f in findings)
