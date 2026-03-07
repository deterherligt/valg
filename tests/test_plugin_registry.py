# tests/test_plugin_registry.py
import importlib
import types
import pytest
from valg.plugins import load_plugins, find_plugin, _plugins


def make_fake_plugin(name: str, pattern: str, table: str = "results"):
    """Create a minimal in-memory plugin module."""
    mod = types.ModuleType(name)
    mod.MATCH = lambda filename: pattern in filename
    mod.TABLE = table
    mod.parse = lambda data, snapshot_at: []
    return mod


def test_load_plugins_populates_registry(monkeypatch):
    """load_plugins() should discover plugins and populate the registry."""
    import valg.plugins as registry
    # Patch iter_modules to return a fake plugin
    fake = make_fake_plugin("fake_plugin", "fakefile")
    monkeypatch.setattr(
        "valg.plugins._plugins", []
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("pkgutil.iter_modules", lambda paths: [
            (None, "fake_plugin", False)
        ])
        mp.setattr("importlib.import_module", lambda name: fake)
        load_plugins()
        assert len(registry._plugins) == 1


def test_find_plugin_returns_matching_plugin():
    import valg.plugins as registry
    fake = make_fake_plugin("fake_geografi", "Region.json")
    registry._plugins.clear()
    registry._plugins.append(fake)
    result = find_plugin("Region.json")
    assert result is fake


def test_find_plugin_returns_none_for_unknown_file():
    import valg.plugins as registry
    fake = make_fake_plugin("fake_geografi", "Region.json")
    registry._plugins.clear()
    registry._plugins.append(fake)
    result = find_plugin("unknown-format-12345.json")
    assert result is None


def test_find_plugin_uses_first_match():
    """When multiple plugins match, the first registered one wins."""
    import valg.plugins as registry
    fake1 = make_fake_plugin("plugin_a", "Region")
    fake2 = make_fake_plugin("plugin_b", "Region")
    registry._plugins.clear()
    registry._plugins.extend([fake1, fake2])
    result = find_plugin("Region.json")
    assert result is fake1


def test_load_plugins_clears_and_reloads(monkeypatch):
    """Calling load_plugins() twice should not double-register plugins."""
    import valg.plugins as registry
    fake = make_fake_plugin("fake_p", "testfile")
    registry._plugins.clear()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("pkgutil.iter_modules", lambda paths: [
            (None, "fake_p", False)
        ])
        mp.setattr("importlib.import_module", lambda name: fake)
        load_plugins()
        count_after_first = len(registry._plugins)
        load_plugins()
        count_after_second = len(registry._plugins)
    assert count_after_second == count_after_first


def test_plugin_interface_contract():
    """A valid plugin must have MATCH, parse, and TABLE."""
    fake = make_fake_plugin("valid_plugin", "test.json", table="results")
    assert callable(fake.MATCH)
    assert callable(fake.parse)
    assert isinstance(fake.TABLE, str)
