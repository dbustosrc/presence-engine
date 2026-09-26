"""Load public test sources from stdin entirely in memory in an HA interpreter."""

import importlib.abc
import importlib.util
import json
import sys
import unittest

sources = json.load(sys.stdin)


class MemoryModules(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in sources:
            return importlib.util.spec_from_loader(fullname, self, is_package=sources[fullname]["package"])
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__file__ = f"<isolated>/{module.__name__.replace('.', '/')}.py"
        exec(compile(sources[module.__name__]["source"], module.__file__, "exec"), module.__dict__)


sys.meta_path.insert(0, MemoryModules())
suite = unittest.defaultTestLoader.loadTestsFromName("test_ha_configuration")
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
