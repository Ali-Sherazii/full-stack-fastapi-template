"""Compile backend/app into native extension modules for shipping.

Cython-compiles every module in the app package to a .c file and then to a
platform-native extension (.so/.pyd), in place, then deletes the .py source
and the intermediate .c file it came from. What's left on disk is only the
compiled binaries plus whatever was never fed to Cython in the first place -
no readable Python source for compiled code ships in the final image.

Run from backend/: python cythonize_build.py
"""

from __future__ import annotations

import pathlib
import shutil

from Cython.Build import cythonize
from setuptools import setup

ROOT = pathlib.Path(__file__).resolve().parent
APP = ROOT / "app"

# Left as plain .py, not fed to Cython at all:
# - app/alembic/**, which Alembic reads and lists by filename - nothing
#   there needs hiding
# - backend_pre_start.py/initial_data.py/tests_pre_start.py, which
#   prestart.sh/tests-start.sh run directly as `python app/foo.py` rather
#   than importing - a compiled extension module can't be executed as a
#   standalone script the way a .py file can, and none of these hold logic
#   worth protecting anyway
# - models.py: User and Item declare a circular relationship
#   (User.items: list[Item], Item.owner: User), so one side always
#   forward-references a class that doesn't exist yet at the point its
#   annotation is evaluated. Cython (even with annotation_typing off, see
#   below) resolves an unresolvable annotation by freezing the *entire*
#   expression into one opaque ForwardRef string instead of only deferring
#   the inner name the way CPython's own annotation evaluation does, and
#   SQLAlchemy's relationship-argument resolver can't parse that shape -
#   it needs the container (list[...]) evaluated for real, with only the
#   class name inside deferred. There's no source-level rewrite that avoids
#   this: quoting the inner name, or wrapping in an explicit
#   Mapped[list[...]], both still leave one direction forward-referencing
#   an undefined name and hit the same failure. This is pure schema (field
#   names/types), already fully visible through the API's OpenAPI schema,
#   so leaving it uncompiled costs nothing worth protecting.
EXCLUDE_NAMES = {
    "backend_pre_start.py",
    "initial_data.py",
    "tests_pre_start.py",
    "models.py",
}


def is_excluded(path: pathlib.Path) -> bool:
    if path.name in EXCLUDE_NAMES:
        return True
    return "alembic" in path.relative_to(APP).parts[:-1]


sources = [str(p) for p in sorted(APP.rglob("*.py")) if not is_excluded(p)]

setup(
    ext_modules=cythonize(
        sources,
        compiler_directives={
            "language_level": "3",
            "binding": True,
            # Keep Cython from freezing type annotations into unevaluated
            # strings: SQLModel/SQLAlchemy resolve relationship targets
            # (e.g. `items: list[Item]`) by evaluating the annotation
            # expression at class-creation time, the way plain CPython
            # does - a frozen string breaks that resolution.
            "annotation_typing": False,
        },
    ),
    script_args=["build_ext", "--inplace"],
)

for source in sources:
    py_path = pathlib.Path(source)
    py_path.unlink()
    py_path.with_suffix(".c").unlink(missing_ok=True)

shutil.rmtree(ROOT / "build", ignore_errors=True)
