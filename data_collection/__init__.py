"""Compatibility package for tool_runner module paths.

Some merged tools reference `data_collection.*` module paths (legacy wiring).
This package provides stable import locations that delegate to the actual
implementations under `src/` and `plugins/`.
"""

