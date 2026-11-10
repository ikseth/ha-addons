"""Las pruebas test_ha_*.py necesitan pytest-homeassistant-custom-component; sin el, se omiten."""
import importlib.util
import os
import sys

if importlib.util.find_spec("pytest_homeassistant_custom_component") is None:
    collect_ignore_glob = ["test_ha_*.py"]
else:
    import pytest

    # custom_components/ debe poder importarse como paquete desde la raiz del repositorio.
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        yield
