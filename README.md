# check-commit-hook

Based on [1] this repository contains a set of BW pre-commit hooks to be run on every git commit, the same hooks are used by the CI/CD pipeline to check the files.

# Hooks

## Checkpatch

Uses Linux kernel checkpatch to check for coding style errors in C code, Makefiles, etc. It uses a custom configuration file to ignore some errors and enforce others.

### Custom configuration file

The script uses a default configuration file located in `checkpatch_hook/data/checkpatch.yaml` but it can be overriden by a custom configuration file and passed to the script using the `--config-file` option.

```
checkpatch --config-file <config_file> <file>
```

The configuration file is a YAML file with the following structure:

```yaml
DIR_CONFIGS:
  <directory1>:
    errors_ignored:
      - <checkpatch option>
      - <checkpatch option>
    max_line_length: <number>
  <directory2>:
    errors_enabled:
      - <checkpatch option>
      - <checkpatch option>
    max_line_length: <number>
```

Note: Either `errors_enabled` or `errors_ignored` are enforced, not both.

#### Magic keys

The configuration file supports some magic keys that make it easier to configure the script.

##### `__default____`

The `__default____` key can be used to apply the same configuration to all the files in the repository.

```yaml
__default____:
  errors_ignored:
    - <checkpatch option>
    - <checkpatch option>
    - ...
  max_line_length: <number>
```

##### `ERRORS_COMMON`

The `ERRORS_ENABLED` key can be used as a placeholder for all the errors enabled, and this needs to be part of `errors_enabled` list to be used.

```yaml
ERRORS_ENABLED:
  - <checkpatch option>
  - <checkpatch option>
  - ...

DIR_CONFIGS:
  <directory>:
    errors_enabled:
      - ERRORS_ENABLED
      - <checkpatch option>
      - <checkpatch option>
      - ...
    max_line_length: <number>
```

##### `IGNORES_COMMON`

The `IGNORES_COMMON` key can be used as a placeholder for all the errors ignored for all the files, and this needs to be part of `errors_ignored` list to be used.

```yaml
IGNORES_COMMON:
  - <checkpatch option>
  - <checkpatch option>
  - ...

DIR_CONFIGS:
  <directory>:
    errors_ignored:
      - IGNORES_COMMON
      - <checkpatch option>
      - <checkpatch option>
    max_line_length: <number>
```

# Usage

## Pre-commit

To use the hooks in your local repository you need to install pre-commit [1] and add the following to your `.pre-commit-config.yaml` file:

```yaml
  - repo: https://github.com/bluwireless/check-commit-hook
    rev: xxxx
    hooks:
      - id: checkpatch
        args: [--config-file, checkpatch_custom.yaml]
```

# References

[1] - https://pre-commit.com/
