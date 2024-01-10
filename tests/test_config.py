#!/usr/bin/env python3
# Copyright (c) Blu Wireless Technology Ltd. 2023, All Rights Reserved


import re
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import mock_open, patch

from checkpatch_hook import ConfigFile


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        self.maxDiff = None
        # This function under test doesn't read the config file, so we can use a dummy file
        self.config_file = ConfigFile(Path("dummy.yaml"))

    def mock_file_read(self, data):
        mock = mock_open(read_data=data)
        patcher = patch("pathlib.Path.open", mock)
        patcher.start()
        return patcher

    def _error_tests(self, config, err_msg):
        patcher = self.mock_file_read(config)
        with patch("sys.stderr", new=StringIO()) as fake_stderr:
            with self.assertRaisesRegex(SystemExit, r"1"):
                self.config_file.load_config()
            error_message = fake_stderr.getvalue()
            self.assertTrue(re.search(err_msg, error_message))
        patcher.stop()

    def test_load_config_with_valid_file(self):
        config = """
        DIR_CONFIGS:
            dir1:
                errors_enabled:
                - error1
                errors_ignored:
                - error2
                max_line_length: '100'
        """
        patcher = self.mock_file_read(config)
        config = self.config_file.load_config()
        self.assertIsInstance(config, dict)
        self.assertIn("DIR_CONFIGS", config)
        patcher.stop()

    def test_load_config_with_missing_mandatory_key(self):
        config = 'INVALID_KEY: ["dir1", "dir2"]'
        self._error_tests(config, r"Missing mandatory key DIR_CONFIGS")

    def test_load_config_with_invalid_value(self):
        config = 'DIR_CONFIGS: ["dir1", "dir2"]'
        self._error_tests(config, r"Invalid type for key DIR_CONFIGS")

    def test_load_config_with_unknown_key(self):
        config = """
        UNKNOWN_KEY: 'value'
        DIR_CONFIGS:
            dir1:
                errors_enabled:
                - error1
                errors_ignored:
                - error2
                max_line_length: '100'
        """
        self._error_tests(config, r"Unknown key UNKNOWN_KEY")

    def test_load_config_with_invalid_type_for_ignored_files(self):
        config = """
        DIR_CONFIGS:
            dir1:
                errors_enabled:
                - error1
                errors_ignored:
                - error2
                max_line_length: '100'
        IGNORED_FILES: 'invalid_type'
        """
        self._error_tests(config, r"Invalid type for key IGNORED_FILES")

    def test_load_config_with_multiple_dir(self):
        config = """
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
        patcher = self.mock_file_read(config)
        config = self.config_file.load_config()
        self.assertIsInstance(config, dict)
        self.assertIn("DIR_CONFIGS", config)
        patcher.stop()


class TestPreProcessDirConfig(unittest.TestCase):
    def setUp(self):
        self.maxDiff = None
        # This function under test doesn't read the config file, so we can use a dummy file
        self.config_file = ConfigFile("dummy.yaml")

    def test_pre_process_dir_config_with_magic_keys_in_dconfig(self):
        config = {
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
            "max_line_length": "120",
        }
        result = self.config_file.pre_process_dir_config(config["DIR_CONFIGS"]["dir1"], config)
        self.assertEqual(result, expected_output)

    def test_pre_process_dir_config_with_no_magic_keys_in_dconfig(self):
        config = {
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
        result = self.config_file.pre_process_dir_config(config["DIR_CONFIGS"]["dir1"], config)
        self.assertEqual(result, expected_output)

    def test_pre_process_dir_config_with_empty_config(self):
        config = {
            "DIR_CONFIGS": {
                "dir1": {
                    "errors_enabled": ["error1", "ERRORS_COMMON"],
                    "errors_ignored": ["error2", "IGNORES_COMMON"],
                }
            },
        }
        self.assertRaisesRegex(
            Exception,
            "Unknown key ERRORS_COMMON",
            self.config_file.pre_process_dir_config,
            config["DIR_CONFIGS"]["dir1"],
            config,
        )

    def test_pre_process_dir_config_with_multiple_dirs(self):
        config = {
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
            "max_line_length": "120",
        }
        expected_output_dir2 = {
            "errors_enabled": ["error3", "common_error1"],
            "errors_ignored": ["error4", "common_error2"],
            "max_line_length": "120",
        }
        result = self.config_file.pre_process_dir_config(
            config["DIR_CONFIGS"]["dir1"], config.copy()
        )
        self.assertEqual(result, expected_output_dir1)
        result = self.config_file.pre_process_dir_config(
            config["DIR_CONFIGS"]["dir2"], config.copy()
        )
        self.assertEqual(result, expected_output_dir2)


if __name__ == "__main__":
    unittest.main()
