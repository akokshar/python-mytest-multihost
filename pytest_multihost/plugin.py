import json
import os
import traceback

import pytest

from pytest_multihost.config import Config, FilterError

try:
    import yaml
except ImportError:
    yaml = None


def pytest_addoption(parser):
    parser.addoption(
        '--multihost-config', dest="multihost_config",
        help="Site configuration for multihost tests")


@pytest.mark.tryfirst
def pytest_load_initial_conftests(args, early_config, parser):
    ns = early_config.known_args_namespace
    if ns.multihost_config:
        if 'BEAKERLIB' not in os.environ:
            raise exit('$BEAKERLIB not set, cannot use --with-beakerlib')

        with open(ns.multihost_config) as conffile:
            if yaml:
                confdict = yaml.safe_load(conffile)
            else:
                try:
                    confdict = json.load(conffile)
                except Exception:
                    traceback.print_exc()
                    raise exit(
                        'Could not load %s. If it is a YAML file, you need '
                        'PyYAML installed.' % ns.multihost_config)
        plugin = MultihostPlugin(confdict)
        pluginmanager = early_config.pluginmanager.register(
            plugin, 'MultihostPlugin')


class MultihostPlugin(object):
    """The Multihost plugin

    The plugin is available as pluginmanager.getplugin('MultihostPlugin'),
    and its presence indicates that multihost testing has been configured.
    """
    def __init__(self, confdict):
        self.confdict = confdict


class MultihostFixture(object):
    """A fixture containing the multihost testing configuration

    Contains the `config`; other attributes may be added to it for convenience.
    """
    def __init__(self, config):
        self.config = config


def make_fixture(request, descriptions, config_class=Config):
    """Create a MultihostFixture, or skip the test

    :param request: The Pytest request object
    :param descriptions:
        Descriptions of wanted domains (see README or Domain.filter)
    :param config_class: Custom Config class to use

    Skips the test if there are not enough resources configured.
    """
    plugin = request.config.pluginmanager.getplugin('MultihostPlugin')
    if not plugin:
        pytest.skip('Multihost tests not configured')
    config = config_class.from_dict(plugin.confdict)
    try:
        config.filter(descriptions)
    except FilterError as e:
        pytest.skip('Not enough resources configured: %s' % e)
    return MultihostFixture(config)
