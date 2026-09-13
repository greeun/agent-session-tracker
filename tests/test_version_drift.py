"""스모크: 릴리스 산출물의 버전 정합성.

CLAUDE.md 는 모든 스킬이 SKILL.md frontmatter 에 `version` 을 유지하도록 의무화하고,
릴리스는 tracker.py 의 `__version__` 과 그 값을 함께 올려야 한다. 한쪽만 올리면
`ast --version` 과 스킬이 서로 다른 버전을 광고한다 — 릴리스 절차에서 실제로 빠뜨리기
쉬운 단계다.

`--version` 플래그의 동작 자체는 test_parser.py::test_version_flag_exits 가 소유한다.
여기서 보는 것은 값이 무엇인지가 아니라 **문서와 코드의 값이 같은지** 라는 교차 파일
불변식이다 (상수 검증이 아니다 — 어느 한쪽만 바꾸면 반드시 깨진다).

frontmatter 만 보던 때, README 의 설치 검증 출력은 `v1.10.0`(존재한 적 없는 버전),
화면 예시는 `v1.1.0` 까지 벌어져 있었다. 독자가 `ast --version` 결과와 직접 비교하는
값이므로, 본문에 적힌 버전도 같은 불변식으로 묶는다."""
import importlib.util
import re
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("tracker_ver", _REPO / "tracker.py")
tk = importlib.util.module_from_spec(_spec)
sys.modules["tracker_ver"] = tk
_spec.loader.exec_module(tk)

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _skill_frontmatter_version() -> str | None:
    """SKILL.md 최상단 `---` 블록에서 `version:` 값을 읽는다 (pyyaml 없이)."""
    text = (_REPO / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        if line.strip().startswith("version:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return None


class TestVersionDrift(unittest.TestCase):
    def test_skill_md_declares_a_version(self):
        self.assertIsNotNone(_skill_frontmatter_version(),
                             "SKILL.md frontmatter 에 version: 이 없다")

    def test_tracker_and_skill_md_agree(self):
        # TC-SMOKE-101
        self.assertEqual(
            tk.__version__, _skill_frontmatter_version(),
            "tracker.py __version__ 과 SKILL.md frontmatter version 이 어긋났다 — "
            "릴리스 때 한쪽만 올린 것으로 보인다")

    def test_version_is_semver(self):
        # TC-SMOKE-102
        self.assertRegex(tk.__version__, _SEMVER)


# 문서 본문이 버전을 광고하는 두 형태. 둘 다 독자가 `ast --version` 출력과
# 나란히 놓고 보는 자리다.
#   README: `# agent-session-tracker v1.4.1`, TUI/list 출력 예시의 헤더
#   SKILL.md: `Main script: tracker.py (stdlib only, Python 3.10+, v1.4.1)`
_DOC_VERSION_PATTERNS = (
    re.compile(r"agent-session-tracker v(\d+\.\d+\.\d+)"),
    re.compile(r"Python 3\.10\+, v(\d+\.\d+\.\d+)"),
)
_DOC_FILES = ("README.md", "README.ko.md", "SKILL.md")


class TestDocumentedVersions(unittest.TestCase):
    """문서 본문에 적힌 버전도 `__version__` 과 같아야 한다.

    frontmatter 만 검사하면 README 쪽은 조용히 낡는다 — 실제로 그렇게 됐다.
    릴리스에서 버전을 올릴 때 이 테스트가 빠뜨린 파일을 지목한다."""

    def _found(self):
        """[(파일명, 버전문자열)] — 문서에서 발견한 모든 버전 표기."""
        out = []
        for name in _DOC_FILES:
            text = (_REPO / name).read_text(encoding="utf-8")
            for pat in _DOC_VERSION_PATTERNS:
                out.extend((name, m.group(1)) for m in pat.finditer(text))
        return out

    def test_every_documented_version_matches(self):
        found = self._found()
        mismatched = [(f, v) for f, v in found if v != tk.__version__]
        self.assertEqual(
            mismatched, [],
            f"문서의 버전이 __version__({tk.__version__})과 어긋났다: {mismatched} — "
            f"릴리스 때 문서를 함께 올리지 않은 것으로 보인다")

    def test_the_patterns_actually_match_something(self):
        # 패턴이 낡아 아무것도 잡지 못하면 위 단언은 공허하게 통과한다.
        found = self._found()
        self.assertGreaterEqual(len(found), 4, f"버전 표기를 찾지 못했다: {found}")
        files = {f for f, _ in found}
        for name in _DOC_FILES:
            self.assertIn(name, files, f"{name} 에서 버전 표기를 찾지 못했다")


if __name__ == "__main__":
    unittest.main()
