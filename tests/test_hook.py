import logging
from pathlib import Path
from textwrap import dedent

from pytest import LogCaptureFixture, MonkeyPatch, raises
from pytest_subprocess import FakeProcess

from checkpatch_hook import logger, main


def _register_pass(fp: FakeProcess) -> None:
    fp.register([fp.any()], returncode=0)


def _register_fail(fp: FakeProcess, stdout: str | None = None) -> None:
    fp.register([fp.any()], returncode=1, stdout=stdout)


def _invoke_hook(monkeypatch: MonkeyPatch, args: list[str]) -> None:
    monkeypatch.setattr("sys.argv", ["checkpatch"] + args)
    main()


def test_default_config_is_applied_pass(fp: FakeProcess, monkeypatch: MonkeyPatch) -> None:
    args = ["--verbose", "test1.c"]
    common_ignores = [
        "BAD_SIGN_OFF",
        "SPDX_LICENSE_TAG",
        "FILE_PATH_CHANGES",
        "NOT_UNIFIED_DIFF",
        "LINUX_VERSION_CODE",
        "CONSTANT_COMPARISON",
        "OPEN_ENDED_LINE",
        "UNNECESSARY_PARENTHESES",
        "GERRIT_CHANGE_ID",
        "COMMIT_LOG_LONG_LINE",
        "EMAIL_SUBJECT",
        "GIT_COMMIT_ID",
    ]

    _register_pass(fp)

    _invoke_hook(monkeypatch, args)

    invocation = " ".join(fp.calls[0])

    for ignore in common_ignores:
        assert ignore in invocation

    assert "--types" not in invocation
    assert "--fix-inplace" not in invocation
    assert "--max-line-length" not in invocation
    assert "--file test1.c" in invocation


def test_default_config_fix_inplace_fail(fp: FakeProcess, monkeypatch: MonkeyPatch) -> None:
    args = ["--fix-inplace", "test1.c"]

    _register_fail(fp)

    with raises(SystemExit):
        _invoke_hook(monkeypatch, args)

    invocation = " ".join(fp.calls[0])

    assert "--fix-inplace" in invocation
    assert "--file test1.c" in invocation


def test_default_config_no_files_pass(fp: FakeProcess, monkeypatch: MonkeyPatch) -> None:
    _register_pass(fp)

    _invoke_hook(monkeypatch, [])

    assert len(fp.calls) == 0


def test_specified_config_is_applied_pass(
    fp: FakeProcess, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "test_config.yaml"
    config_text = dedent(
        """\
    DIR_CONFIGS:
        __default__:
            errors_ignored:
            - UNNECESSARY_PARENTHESES
            max_line_length: '120'
        dir2:
            errors_enabled:
            - GERRIT_CHANGE_ID
            max_line_length: '100'
    """
    )
    config_path.write_text(config_text)
    args = ["--config-file", str(config_path), "test1.c", "dir2/test2.h"]

    _register_pass(fp)
    _register_pass(fp)

    _invoke_hook(monkeypatch, args)

    assert len(fp.calls) == 2

    invocation_default = " ".join(fp.calls[0])
    invocation_dir2 = " ".join(fp.calls[1])

    assert "--ignore UNNECESSARY_PARENTHESES" in invocation_default
    assert "--types" not in invocation_default
    assert "--fix-inplace" not in invocation_default
    assert "--max-line-length=120" in invocation_default
    assert "--file test1.c" in invocation_default
    assert "test2.h" not in invocation_default

    assert "--ignore" not in invocation_dir2
    assert "--types GERRIT_CHANGE_ID" in invocation_dir2
    assert "--fix-inplace" not in invocation_dir2
    assert "--max-line-length=100" in invocation_dir2
    assert "--file dir2/test2.h" in invocation_dir2
    assert "test1.c" not in invocation_dir2


def test_errors_returned(
    fp: FakeProcess, monkeypatch: MonkeyPatch, tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    config_path = tmp_path / "test_config.yaml"
    config_text = dedent(
        """\
    DIR_CONFIGS:
        __default__:
            errors_ignored:
            - UNNECESSARY_PARENTHESES
            max_line_length: '120'
        dir2:
            errors_enabled:
            - GERRIT_CHANGE_ID
            max_line_length: '100'
    """
    )
    config_path.write_text(config_text)
    args = ["--config-file", str(config_path), "test1.c", "dir2/test2.h"]

    _register_fail(fp, "test1.c:101: checkpatch: WARNING: struct  should normally be const")
    _register_pass(fp)

    with caplog.at_level(logging.ERROR, logger.name):
        with raises(SystemExit):
            _invoke_hook(monkeypatch, args)

        assert "WARNING: struct  should normally be const" in caplog.records[0].message
