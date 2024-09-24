#!/usr/bin/env python3

import argparse
import importlib.resources
import logging
import sys
from collections import defaultdict
from logging import getLogger
from pathlib import Path
from subprocess import PIPE, run
from typing import DefaultDict

import yaml

logging.basicConfig()
logger = getLogger(__name__)

checkpatch_script_path = importlib.resources.files("checkpatch_hook.scripts").joinpath(
    "checkpatch.pl"
)


def _parse_args() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        default=[],
        help="Files to check",
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=importlib.resources.files("checkpatch_hook.data").joinpath(
            "checkpatch.yaml",
        ),
        help="Path to config file",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--fix-inplace",
        action="store_true",
        help="Enable checkplace in-place fixes",
    )
    return vars(parser.parse_args())


class ConfigFile:
    DEFAULT_DIR_KEY = "__default__"
    mandatory_keys = ["DIR_CONFIGS"]
    # TODO: with YAML anchors there wouldn't really be a need for this approach
    magic_error_keys = {"errors_enabled": "ERRORS_COMMON", "errors_ignored": "IGNORES_COMMON"}
    optional_keys = ["IGNORED_FILES"]
    # TODO: Use schema based validation e.g., cfgv

    def __init__(self, config_file_path: Path):
        self.config_file_path = config_file_path

    def load_config(self) -> dict:
        try:
            with self.config_file_path.open("r") as file:
                config = yaml.safe_load(file)
            if config is None or not isinstance(config, dict) or not config:
                raise RuntimeError("Config file is empty")
            for key in self.mandatory_keys:
                if key not in config:
                    raise RuntimeError(f"Missing mandatory key {key} in {self.config_file_path}")
                if not isinstance(config[key], dict) or not config[key]:
                    raise RuntimeError(f"Invalid type for key {key} in {self.config_file_path}")
            # Check for unknown keys
            for key in config.keys():
                if key not in self.mandatory_keys + self.optional_keys + list(
                    self.magic_error_keys.values()
                ):
                    raise RuntimeError(f"Unknown key {key} in {self.config_file_path}")
            if not isinstance(config.get("IGNORED_FILES", []), list):
                raise RuntimeError(f"Invalid type for key IGNORED_FILES in {self.config_file_path}")
            return config
        except FileNotFoundError:
            logger.error(f"Config file not found: {self.config_file_path}")
            sys.exit(1)
        except yaml.YAMLError as e:
            logger.error(f"Error loading YAML config file: {e}")
            sys.exit(1)
        except RuntimeError as e:
            logger.error(f"Error loading YAML config file: {e}")
            sys.exit(1)

    def pre_process_dir_config(self, dconfig: dict, config: dict) -> dict:
        # Default values
        dconfig["errors_enabled"] = dconfig.get("errors_enabled", [])
        dconfig["errors_ignored"] = dconfig.get("errors_ignored", [])
        dconfig["max_line_length"] = dconfig.get("max_line_length", None)

        # Process magic keys
        for key, value in self.magic_error_keys.items():
            if key in dconfig and value in dconfig[key]:
                if value not in config.keys():
                    logger.error(f"Unknown key {value} in {self.config_file_path}")
                    sys.exit(1)
                dconfig[key].extend(config[value])
                dconfig[key].remove(value)
        return dconfig


def pre_commit_hook(config_file: Path, commit_files: list[Path], fix_inplace: bool) -> None:
    config_file_obj = ConfigFile(config_file)
    config = config_file_obj.load_config()
    logger.debug(f"Config file @ {config_file.resolve()}")

    result = True
    errors: DefaultDict[str, list] = defaultdict(list)
    # accumulate checkpatch errors for each configured dir
    for config_dir, dconfig in config["DIR_CONFIGS"].items():
        # Special case for the default config
        if config_dir == ConfigFile.DEFAULT_DIR_KEY:
            config_dir = "."
        config_dir = Path(config_dir)

        post_dconfig = config_file_obj.pre_process_dir_config(dconfig, config)
        patch_files = [
            p
            for p in commit_files
            if check_config_applicable(config, config_dir, p)
            and p not in config.get("IGNORED_FILES", [])
            and not p.is_symlink()
        ]
        if patch_files:
            result_dir = _run_checkpatch(
                patch_files, fix_inplace, errors, config_dir, **post_dconfig
            )
            if not result_dir:
                result = result_dir
        else:
            logger.debug(f"No files to check in {config_dir}")

    # log errors
    for filename, file_errors in errors.items():
        for error in file_errors:
            logger.error("%s:%s: %s", filename, error["line"], error["message"])
    if not result:
        sys.exit(1)


def check_config_applicable(config: dict, config_dir: Path, path: Path) -> bool:
    if str(config_dir) != ".":
        return path.is_relative_to(config_dir)
    for other_config_dir in config["DIR_CONFIGS"].keys():
        if other_config_dir == ConfigFile.DEFAULT_DIR_KEY:
            continue
        other_config_path = Path(other_config_dir)
        if path.is_relative_to(other_config_path):
            return False
    return True


def _run_checkpatch(
    patch_files: list[Path],
    fix_inplace: bool,
    errors: DefaultDict[str, list],
    config_dir: Path,
    errors_enabled: list,
    errors_ignored: list,
    max_line_length: int | str | None,
) -> bool:
    cmd = [
        str(checkpatch_script_path),
        "--strict",  # Be more annoying
        "--no-tree",  # No kernel source tree present
        # Some stuff to make parsing easier
        "--emacs",
        "--terse",
        "--showfile",
        "--no-summary",
        "--color=never",
        "--no-signoff",  # Don't require Signed-Off-By
    ]

    if fix_inplace:
        cmd += ["--fix-inplace"]

    if errors_ignored:
        cmd += ["--ignore", ",".join(errors_ignored)]
    elif errors_enabled:
        cmd += ["--types", ",".join(errors_enabled)]
    if max_line_length is not None:
        cmd += [f"--max-line-length={max_line_length}"]

    cmd += ["--file", *[str(p) for p in patch_files]]

    logger.debug(f"Running checkpatch in {str(config_dir)} with: {' '.join(cmd)}")
    result = run(cmd, stdout=PIPE)

    if result.returncode != 0:
        _process_checkpatch_errors(result.stdout.decode(), errors)
        return False
    return True


def _process_checkpatch_errors(output: str, errors: DefaultDict[str, list]) -> None:
    for line in output.splitlines():
        filename, line_num_str, message = line.split(":", maxsplit=2)
        if filename == "":
            filename = "/COMMIT_MSG"
        errors[filename].append(
            {
                "line": int(line_num_str),
                "message": f"checkpatch: {message.strip()}",
            }
        )


def main() -> None:
    """
    Entry point to be used when run as hook script.
    """
    args = _parse_args()
    if args["verbose"]:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    pre_commit_hook(args["config_file"], args["files"], args["fix_inplace"])


if __name__ == "__main__":
    main()
