# valg/plugins/__init__.py
import importlib
import logging
import pkgutil
from pathlib import Path

log = logging.getLogger(__name__)

_plugins: list = []


def load_plugins() -> None:
    """Discover and load all plugins in the valg/plugins/ directory."""
    global _plugins
    _plugins.clear()
    pkg_dir = Path(__file__).parent
    for _, name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        try:
            mod = importlib.import_module(f"valg.plugins.{name}")
            if hasattr(mod, "MATCH") and hasattr(mod, "parse") and hasattr(mod, "TABLE"):
                _plugins.append(mod)
                log.debug("Loaded plugin: %s -> %s", name, mod.TABLE)
            else:
                log.warning("Plugin %s missing MATCH, parse, or TABLE — skipped", name)
        except Exception as e:
            log.error("Failed to load plugin %s: %s", name, e)


def find_plugin(filename: str):
    """Return the first plugin whose MATCH function returns True for filename, or None."""
    for plugin in _plugins:
        try:
            if plugin.MATCH(filename):
                return plugin
        except Exception as e:
            log.warning("Plugin %s MATCH raised: %s", plugin, e)
    return None
