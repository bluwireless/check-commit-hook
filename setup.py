from pathlib import Path

from setuptools import find_packages, setup

_version_file_path = Path(__file__).parent.resolve() / ".version"
with _version_file_path.open("r") as file:
    _version = file.read().strip()


setup(
    name="check-commit-hook",
    version=_version,
    entry_points={
        "console_scripts": [
            "checkpatch=checkpatch_hook:main",
        ],
    },
    install_requires=[
        "pyyaml",
    ],
    # These should be bundled together
    scripts=[
        "checkpatch_hook/scripts/checkpatch.pl",
        "checkpatch_hook/data/const_structs.checkpatch",
        "checkpatch_hook/data/spelling.txt",
    ],
    package_data={
        "checkpatch_hook": [
            "data/checkpatch.yaml",
        ],
    },
    packages=find_packages(),
    description="BWT check commit hooks",
    python_requires=">=3.10",
)
