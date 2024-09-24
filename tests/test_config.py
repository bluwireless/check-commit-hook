import logging
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pytest import fixture, raises

from checkpatch_hook import ConfigFile


@fixture(scope="function")
def config_file(tmp_path: Path) -> ConfigFile:
    return ConfigFile(tmp_path / "test_config.yaml")


def _setup_config_file(config_file: ConfigFile, config_text: str) -> None:
    config_file.config_file_path.write_text(config_text)


def _error_tests(config_file: ConfigFile, err_msg: str) -> None:
    dut_logger = logging.getLogger("checkpatch_hook")
    with patch.object(dut_logger, "error") as mock_logger:
        with raises(SystemExit):
            config_file.load_config()

        assert any(re.search(err_msg, call.args[0]) for call in mock_logger.mock_calls)


def test_load_config_with_valid_file(config_file: ConfigFile) -> None:
    config_text = """
    DIR_CONFIGS:
        dir1:
            errors_enabled:
            - error1
            errors_ignored:
            - error2
            max_line_length: '100'
    """
    _setup_config_file(config_file, config_text)
    config = config_file.load_config()
    assert isinstance(config, dict)
    # TODO: necessary to have this level?
    assert "DIR_CONFIGS" in config


def test_load_config_with_missing_mandatory_key(config_file: ConfigFile) -> None:
    config_text = 'INVALID_KEY: ["dir1", "dir2"]'
    _setup_config_file(config_file, config_text)
    _error_tests(config_file, r"Missing mandatory key DIR_CONFIGS")


def test_load_config_with_invalid_value(config_file: ConfigFile) -> None:
    config_text = 'DIR_CONFIGS: ["dir1", "dir2"]'
    _setup_config_file(config_file, config_text)
    _error_tests(config_file, r"Invalid type for key DIR_CONFIGS")


def test_load_config_with_unknown_key(config_file: ConfigFile) -> None:
    config_text = """
    UNKNOWN_KEY: 'value'
    DIR_CONFIGS:
        dir1:
            errors_enabled:
            - error1
            errors_ignored:
            - error2
            max_line_length: '100'
    """
    _setup_config_file(config_file, config_text)
    _error_tests(config_file, r"Unknown key UNKNOWN_KEY")


def test_load_config_with_invalid_type_for_ignored_files(config_file: ConfigFile) -> None:
    config_text = """
    DIR_CONFIGS:
        dir1:
            errors_enabled:
            - error1
            errors_ignored:
            - error2
            max_line_length: '100'
    IGNORED_FILES: 'invalid_type'
    """
    _setup_config_file(config_file, config_text)
    _error_tests(config_file, r"Invalid type for key IGNORED_FILES")


def test_load_config_with_multiple_dir(config_file: ConfigFile) -> None:
    config_text = """
    DIR_CONFIGS:
        dir1:
            errors_enabled:
            - error1
            errors_ignored:
            - error2
            max_line_length: '100'
        dir2:
            errors_enabled:
            - error1
            errors_ignored:
            - error2
            max_line_length: '100'
    """
    _setup_config_file(config_file, config_text)
    config = config_file.load_config()
    assert "DIR_CONFIGS" in config
    assert "dir1" in config["DIR_CONFIGS"]
    assert "dir2" in config["DIR_CONFIGS"]


def test_pre_process_dir_config_with_magic_keys_in_dconfig(config_file: ConfigFile) -> None:
    config: dict[str, Any] = {
        "ERRORS_COMMON": ["common_error1"],
        "IGNORES_COMMON": ["common_error2"],
        "DIR_CONFIGS": {
            "dir1": {
                "errors_enabled": ["error1", "ERRORS_COMMON"],
                "errors_ignored": ["error2", "IGNORES_COMMON"],
            }
        },
    }
    expected_output = {
        "errors_enabled": ["error1", "common_error1"],
        "errors_ignored": ["error2", "common_error2"],
        "max_line_length": None,
    }
    result = config_file.pre_process_dir_config(config["DIR_CONFIGS"]["dir1"], config)
    assert result == expected_output


def test_pre_process_dir_config_with_no_magic_keys_in_dconfig(config_file: ConfigFile) -> None:
    config: dict[str, Any] = {
        "ERRORS_COMMON": ["common_error1"],
        "IGNORES_COMMON": ["common_error2"],
        "DIR_CONFIGS": {
            "dir1": {
                "errors_enabled": ["error1"],
                "errors_ignored": ["error2"],
                "max_line_length": "100",
            }
        },
    }
    expected_output = {
        "errors_enabled": ["error1"],
        "errors_ignored": ["error2"],
        "max_line_length": "100",
    }
    result = config_file.pre_process_dir_config(config["DIR_CONFIGS"]["dir1"], config)
    assert result == expected_output


def test_pre_process_dir_config_with_empty_config(config_file: ConfigFile) -> None:
    config: dict[str, Any] = {
        "DIR_CONFIGS": {
            "dir1": {
                "errors_enabled": ["error1", "ERRORS_COMMON"],
                "errors_ignored": ["error2", "IGNORES_COMMON"],
            }
        },
    }
    with raises(SystemExit):
        config_file.pre_process_dir_config(config["DIR_CONFIGS"]["dir1"], config)


def test_pre_process_dir_config_with_multiple_dirs(config_file: ConfigFile) -> None:
    config: dict[str, Any] = {
        "ERRORS_COMMON": ["common_error1"],
        "IGNORES_COMMON": ["common_error2"],
        "DIR_CONFIGS": {
            "dir1": {
                "errors_enabled": ["error1", "ERRORS_COMMON"],
                "errors_ignored": ["error2", "IGNORES_COMMON"],
            },
            "dir2": {
                "errors_enabled": ["error3", "ERRORS_COMMON"],
                "errors_ignored": ["error4", "IGNORES_COMMON"],
            },
        },
    }
    expected_output_dir1 = {
        "errors_enabled": ["error1", "common_error1"],
        "errors_ignored": ["error2", "common_error2"],
        "max_line_length": None,
    }
    expected_output_dir2 = {
        "errors_enabled": ["error3", "common_error1"],
        "errors_ignored": ["error4", "common_error2"],
        "max_line_length": None,
    }
    result = config_file.pre_process_dir_config(config["DIR_CONFIGS"]["dir1"], config.copy())
    assert result == expected_output_dir1
    result = config_file.pre_process_dir_config(config["DIR_CONFIGS"]["dir2"], config.copy())
    assert result == expected_output_dir2
