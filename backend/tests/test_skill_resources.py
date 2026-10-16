import json
import tempfile
import unittest
from pathlib import Path

from core.skill_loader import SkillManager


ROOT = Path(__file__).resolve().parents[1]
TOOLS = {"get_enrollment", "advise_transfer", "prepare_transfer",
         "get_application_status", "assess_free_transfer"}


class SkillResourceTests(unittest.TestCase):
    def setUp(self):
        self.manager = SkillManager(str(ROOT / "skills"))
        self.manager.load()

    def test_resources_are_not_independent_skills(self):
        self.assertEqual([], self.manager.errors)
        self.assertFalse(any("references" in Path(s.path).parts or
                             "templates" in Path(s.path).parts or
                             Path(s.path).name == "resources.json" for s in self.manager.skills))

    def test_continuation_and_role_scoping(self):
        prompt = self.manager.prompt_for("下午的", "academic_service", TOOLS)
        self.assertIn("[reference: references/transfer_workflow.md]", prompt)
        self.assertIn("[template: templates/transfer_draft.md]", prompt)
        self.assertNotIn("[reference: references/policy_evidence.md]", prompt)
        prompt = self.manager.prompt_for("转班", "course_consultation", TOOLS)
        self.assertNotIn("[reference:", prompt)
        self.assertNotIn("[template:", prompt)

    def test_missing_tools_do_not_load_workflow_or_grant_permissions(self):
        prompt = self.manager.prompt_for("免费资格", "fees_entitlements", [])
        self.assertIn("缺少工具", prompt)
        self.assertNotIn("[reference: references/policy_evidence.md]", prompt)
        prompt = self.manager.prompt_for("免费资格", "fees_entitlements", TOOLS)
        self.assertIn("[reference: references/policy_evidence.md]", prompt)
        self.assertIn("[template: templates/eligibility_result.md]", prompt)
        self.assertNotIn("[template: templates/transfer_draft.md]", prompt)

    def test_traversal_rejected_and_legacy_file_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "package"
            package.mkdir()
            (root / "legacy.md").write_text("# legacy\nLegacy instructions", encoding="utf-8")
            (package / "SKILL.md").write_text("# package\nWorkflow", encoding="utf-8")
            (package / "resources.json").write_text(json.dumps([
                {"path": "../legacy.md", "kind": "reference"}]), encoding="utf-8")
            manager = SkillManager(folder)
            manager.load()
            self.assertEqual(["legacy"], [s.name for s in manager.skills])
            self.assertEqual(1, len(manager.errors))

    def test_resources_are_read_lazily_and_reload_removes_deleted_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "SKILL.md").write_text("# demo\nEntry", encoding="utf-8")
            resource = root / "guide.md"
            resource.write_text("FIRST", encoding="utf-8")
            manifest = root / "resources.json"
            manifest.write_text(json.dumps([{"path": "guide.md", "kind": "reference"}]), encoding="utf-8")
            manager = SkillManager(folder)
            manager.load()
            resource.write_text("UPDATED", encoding="utf-8")
            self.assertIn("UPDATED", manager.prompt_for("hello"))
            resource.unlink()
            self.assertIn("资源不可用", manager.prompt_for("hello"))
            manifest.write_text("[]", encoding="utf-8")
            manager.reload()
            self.assertNotIn("资源不可用", manager.prompt_for("hello"))


if __name__ == "__main__":
    unittest.main()
