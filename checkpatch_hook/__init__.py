#!/usr/bin/env python3

import argparse
import importlib.resources
import logging
import sys
from collections import defaultdict
from datetime import datetime
from logging import getLogger
from pathlib import Path
from subprocess import PIPE, check_output, run
from typing import DefaultDict

import yaml

logging.basicConfig()
logger = getLogger(__name__)
logger.setLevel(logging.INFO)


def _parse_args() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--commit-msg",
        action="store_true",
        help="Indicates that the commit-msg hook has been invoked",
    )
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
    magic_error_keys = {"errors_enabled": "ERRORS_COMMON", "errors_ignored": "IGNORES_COMMON"}
    optional_keys = ["IGNORED_FILES"]
    # TODO: Use schema based validation e.g., cfgv

    def __init__(self, config_file: Path):
        self.config_file = config_file

    def load_config(self) -> dict:
        try:
            with self.config_file.open("r") as file:
                config = yaml.safe_load(file)
            if config is None or not isinstance(config, dict) or not config:
                raise RuntimeError("Config file is empty")
            for key in self.mandatory_keys:
                if key not in config:
                    raise RuntimeError(f"Missing mandatory key {key} in {self.config_file}")
                if not isinstance(config[key], dict) or not config[key]:
                    raise RuntimeError(f"Invalid type for key {key} in {self.config_file}")
            # Check for unknown keys
            for key in config.keys():
                if key not in self.mandatory_keys + self.optional_keys + list(
                    self.magic_error_keys.values()
                ):
                    raise RuntimeError(f"Unknown key {key} in {self.config_file}")
            if not isinstance(config.get("IGNORED_FILES", []), list):
                raise RuntimeError(f"Invalid type for key IGNORED_FILES in {self.config_file}")
            return config
        except FileNotFoundError:
            logger.error(f"Config file not found: {self.config_file}")
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
                    raise RuntimeError(f"Unknown key {value} in {self.config_file}")
                dconfig[key].extend(config[value])
                dconfig[key].remove(value)
        return dconfig


def pre_commit_hook(config_file: Path, commit_files: list[Path], fix_inplace: bool) -> None:
    config_file_obj = ConfigFile(config_file)
    config = config_file_obj.load_config()
    logger.debug(f"Config file @ {config_file.resolve()}")

    errors: DefaultDict[str, list] = defaultdict(lambda: [])
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
            if p.is_relative_to(config_dir)
            and p not in config.get("IGNORED_FILES", [])
            and not p.is_symlink()
        ]
        if patch_files:
            _run_checkpatch(patch_files, fix_inplace, errors, config_dir, **post_dconfig)
        else:
            logger.debug(f"No files to check in {config_dir}")

    # print errors
    for filename, f_errors in errors.items():
        logger.error(f"{filename}:")
        for error in f_errors:
            logger.error(f'  {error["line"]}: {error["message"]}')
    if errors:
        sys.exit(1)


def _run_checkpatch(
    patch_files: list[Path],
    fix_inplace: bool,
    errors: DefaultDict[str, list],
    config_dir: Path,
    errors_enabled: list,
    errors_ignored: list,
    max_line_length: int | str | None,
) -> None:
    cmd = [
        "checkpatch.pl",
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


def commit_msg_hook(commit_files: list[Path]) -> None:
    commit_msg = _read_commit_msg(commit_files)
    patch = _msg_to_patch(commit_msg)
    # TODO: make shared constant if possible
    cmd = [
        "checkpatch.pl",
        "--strict",  # Be more annoying
        "--no-tree",  # No kernel source tree present
        # Some stuff to make parsing easier
        "--emacs",
        "--terse",
        "--showfile",
        "--no-summary",
        "--color=never",
        "--no-signoff",  # Don't require Signed-Off-By
        # ignore some commit message errors
        "--ignore",
        "GERRIT_CHANGE_ID,COMMIT_LOG_LONG_LINE,EMAIL_SUBJECT,GIT_COMMIT_ID",
    ]

    logger.debug("Running checkpatch on commit message")
    result = run(cmd, input=patch.encode(), stdout=PIPE)

    if result.returncode != 0:
        errors: DefaultDict[str, list] = defaultdict(lambda: [])
        _process_checkpatch_errors(result.stdout.decode(), errors)
        # TODO: more copy and paste
        # print errors
        for filename, f_errors in errors.items():
            logger.error(f"{filename}:")
            for error in f_errors:
                logger.error(f'  {error["line"]}: {error["message"]}')
        if errors:
            sys.exit(1)


def _read_commit_msg(commit_files: list[Path]) -> str:
    if commit_files and commit_files[0].is_file():
        logger.debug(f"Reading commit message from {commit_files[0]}")
        commit_msg = commit_files[0].read_text()
    else:
        logger.debug("Reading commit message from log")
        commit_msg = _get_commit_msg_from_log()
    logger.debug(f"Commit message: {commit_msg}")
    return commit_msg


def _get_commit_msg_from_log() -> str:
    # sha = check_output(["git", "log", "--no-merges", "--format=%H", "-n1"]).decode()
    # logger.debug(f"Commit SHA: {sha}")
    msg = check_output(["git", "log", "--no-merges", "--format=%B", "-n1"]).decode()
    # logger.debug(f"Commit message: {msg}")
    return msg


# template used to add a patch-style header to a commit message
PATCH_TEMPLATE = """\
From: A Non <a.non@somewhere.com>
Date: {current_datetime}
Subject: [PATCH] {commit_msg}
---
 dummy.txt | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)

diff --git a/dummy.txt b/dummy.txt
index 0000000..1111111 100644
--- a/dummy.txt
+++ b/dummy.txt
@@ -0,0 +1 @@
+dummy
--
"""


def _msg_to_patch(commit_msg: str) -> str:
    return PATCH_TEMPLATE.format(
        commit_msg=commit_msg,
        current_datetime=datetime.now().strftime("%a, %d %b %Y %H:%M:%S %z"),
    )


def main() -> None:
    """
    Entry point to be used when run as hook script.
    """
    args = _parse_args()
    logger.debug(f"Running with args: {args}")
    if args["verbose"]:
        logger.setLevel(logging.DEBUG)

    if args["commit_msg"]:
        commit_msg_hook(args["files"])
    else:
        pre_commit_hook(args["config_file"], args["files"], args["fix_inplace"])


if __name__ == "__main__":
    main()
