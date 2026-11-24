import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "antigravity" / "install.sh"


class SandboxSafeInstallTests(unittest.TestCase):
    def _run(self, editable: bool, user_config: bool = False):
        tmp = Path(tempfile.mkdtemp())
        home = tmp / "home"
        venvs = tmp / "venvs"
        dist = venvs / "obsidian-cli-memory-bank" / "lib" / "python3.12" / "site-packages" / "obsidian_cli_memory_bank-0.1.0.dist-info"
        dist.mkdir(parents=True)
        (dist / "direct_url.json").write_text(
            '{"dir_info": {"editable": %s}, "url": "file:///x"}' % ("true" if editable else "false")
        )
        user_state = home / ".local" / "state" / "obsidian-cli-memory-bank" / "vault_config.json"
        if user_config:
            user_state.parent.mkdir(parents=True)
            user_state.write_text('{"mine": 1}')
        bindir = tmp / "bin"
        bindir.mkdir()
        log = tmp / "pipx.log"
        stub = bindir / "pipx"
        stub.write_text(
            "#!/bin/bash\n"
            f'if [[ "$1" == environment ]]; then echo "{venvs}"; exit 0; fi\n'
            f'echo "$@" >> "{log}"\n'
        )
        stub.chmod(0o755)
        # A fake repo state file, so the test never reads George's real config.
        fake_repo = tmp / "repo"
        (fake_repo / "antigravity").mkdir(parents=True)
        (fake_repo / "state").mkdir()
        (fake_repo / "state" / "vault_config.json").write_text('{"default_vault_path": "/v"}')
        script = fake_repo / "antigravity" / "install.sh"
        script.write_text(INSTALL.read_text())
        env = dict(os.environ, HOME=str(home), PATH=f"{bindir}:/usr/bin:/bin")
        result = subprocess.run(
            ["bash", str(script), "--sandbox-safe", "--workspace", str(tmp / "ws")],
            capture_output=True, text=True, env=env,
        )
        calls = log.read_text() if log.exists() else ""
        return result, calls, user_state, fake_repo

    def test_editable_install_is_reinstalled_and_config_copied(self):
        result, calls, user_state, repo = self._run(editable=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"install --force {repo}", calls)
        self.assertEqual(user_state.read_text(), '{"default_vault_path": "/v"}')
        self.assertEqual(oct(user_state.stat().st_mode & 0o777), "0o600")

    def test_regular_install_and_existing_config_are_left_alone(self):
        result, calls, user_state, _ = self._run(editable=False, user_config=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("install", calls)
        self.assertEqual(user_state.read_text(), '{"mine": 1}')


if __name__ == "__main__":
    unittest.main()
