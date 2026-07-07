import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class LinkingTests(unittest.TestCase):
    def test_create_resolve_and_remove_posix_symlink(self):
        from tool_hub.linking import create_link, is_managed_link, remove_link, resolve_link

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            target = Path(tmp) / "target"
            source.mkdir()

            create_link(source, target)

            self.assertTrue(is_managed_link(target))
            self.assertEqual(resolve_link(target).resolve(), source.resolve())

            remove_link(target)
            self.assertFalse(target.exists())
            self.assertTrue(source.exists())

    def test_remove_link_rejects_real_directory(self):
        from tool_hub.linking import LinkError, remove_link

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "real"
            directory.mkdir()

            with self.assertRaises(LinkError):
                remove_link(directory)

            self.assertTrue(directory.exists())

    def test_create_link_uses_windows_junction_strategy(self):
        from tool_hub.linking import create_link

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            target = Path(tmp) / "target"
            source.mkdir()
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            with patch("tool_hub.linking._is_windows", return_value=True), patch(
                "tool_hub.linking.subprocess.run", return_value=completed
            ) as run:
                create_link(source, target)

            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][:4], ["cmd", "/c", "mklink", "/J"])
            self.assertEqual(run.call_args.args[0][4:], [str(target), str(source)])

    def test_windows_junction_can_be_removed_with_rmdir(self):
        from tool_hub.linking import remove_link

        fake_path = Path("C:/agent/skills/demo")

        with patch("tool_hub.linking._is_junction", return_value=True), patch(
            "tool_hub.linking.os.rmdir"
        ) as rmdir:
            remove_link(fake_path)

        rmdir.assert_called_once_with(fake_path)

    def test_windows_junction_tag_detection_for_python_39_to_311(self):
        from tool_hub.linking import _WINDOWS_JUNCTION_TAG, is_managed_link

        fake_stat = Mock()
        fake_stat.st_reparse_tag = _WINDOWS_JUNCTION_TAG

        with patch("tool_hub.linking._is_windows", return_value=True), patch(
            "tool_hub.linking.os.lstat", return_value=fake_stat
        ):
            self.assertTrue(is_managed_link(Path("C:/agent/skills/demo")))


if __name__ == "__main__":
    unittest.main()
