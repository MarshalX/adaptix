import importlib
from pathlib import Path

import pytest
from pytest import param, register_assert_rewrite

from adaptix._internal.feature_requirement import HAS_PY_310

DOCS_ROOT_PARENT = Path(__file__).parent.parent
DOCS_EXAMPLES_ROOT = DOCS_ROOT_PARENT / 'docs' / 'examples'
EXCLUDE = ['__init__.py']
GLOB = '*.py'


def pytest_generate_tests(metafunc):
    if 'import_path' not in metafunc.fixturenames:
        return

    paths_to_test = [
        sub_path
        for sub_path in DOCS_EXAMPLES_ROOT.rglob(GLOB)
        if sub_path.name not in EXCLUDE and not sub_path.is_dir()
    ]
    metafunc.parametrize(
        ["import_path", "case_id"],
        [
            param(
                '.'.join((path_to_test.parent / path_to_test.stem).relative_to(DOCS_ROOT_PARENT).parts),
                str((path_to_test.parent / path_to_test.stem).relative_to(DOCS_EXAMPLES_ROOT)),
                id=str((path_to_test.parent / path_to_test.stem).relative_to(DOCS_EXAMPLES_ROOT)),
            )
            for path_to_test in paths_to_test
        ]
    )


def test_example(import_path: str, case_id: str):
    if case_id == 'tutorial/struct_path_renderer_filter' and not HAS_PY_310:
        pytest.skip('Need Python >= 3.10')

    register_assert_rewrite(import_path)
    importlib.import_module(import_path)
