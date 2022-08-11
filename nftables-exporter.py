#!/usr/bin/env python3
from collections import defaultdict, deque
from pathlib import Path

import argparse
import hashlib
import json
import logging
import os
import sys
import prometheus_client
import subprocess
import tarfile
import time
import urllib.request, urllib.error

log = logging.getLogger('nftables-exporter')

# based on https://stackoverflow.com/a/10551190
class EnvDefault(argparse.Action):
    """ Custom argparse action that adds the ability to use environment
        variables as default (which can be overridden using regular args).
    """

    def __init__(self, envvar, required=True, default=None, **kwargs):
        self.envvar=envvar
        if envvar in os.environ:
            default = os.environ[envvar]
        if required and default:
            required = False
        super(EnvDefault, self).__init__(default=default, required=required, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)

# based on https://stackoverflow.com/a/24662215
class EnvDefaultsHelpFormatter(argparse.ArgumentDefaultsHelpFormatter   ):
    """ Builds on top of argparse.ArgumentDefaultsHelpFormatter and appends
        environment variable names (format '[envvar: <varname>]').
    """

    def _get_help_string(self, action):
        help = super()._get_help_string(action)
        if action.dest != 'help':
            help += f' [envvar: {format(action.envvar)}]'
        return help


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=
        'A Prometheus Exporter that exposes some of nftables (https://nftables.org/projects/nftables/index.html) state as scrapable metrics. This includes a) the size of certain objects (ruleset, chains, maps, sets) b) packet and byte values of named counters c) packet and byte values of rules that use a counter and addirionally specify a comment. Care must be taken that names/comments are unique within the scope of a table.',
        formatter_class=EnvDefaultsHelpFormatter)
    parser.add_argument( '-a', '--address', action=EnvDefault, envvar='NFTABLES_EXPORTER_ADDRESS',default='0.0.0.0', required=False, help='listen address')
    parser.add_argument( '-p', '--port', action=EnvDefault, envvar='NFTABLES_EXPORTER_PORT', type=int, default=9630, help='listen port')
    parser.add_argument( '-u', '--update', action=EnvDefault, envvar='NFTABLES_EXPORTER_UPDATE_PERIOD', type=int, default=60, help='update interval in seconds')
    parser.add_argument( '-n', '--namespace', action=EnvDefault, envvar='NFTABLES_EXPORTER_NAMESPACE', default='nftables', help='all metrics are prefixed with the namespace')
    parser.add_argument( '-l', '--loglevel', action=EnvDefault, envvar='NFTABLES_EXPORTER_LOG_LEVEL', default="info", help='one of the log levels from pythons `logging` module')
    parser.add_argument( '--mmlicense', action=EnvDefault, envvar='MAXMIND_LICENSE_KEY', required=False, help="license key for maxmind geoip database (optional, if not both mmlicense and mmedition are specified, the feature is disabled)")
    parser.add_argument( '--mmedition', action=EnvDefault, envvar='MAXMIND_DATABASE_EDITION', default="GeoLite2-Country", help='maxmind database edition (optional, if not both mmedition and mmlicense are specified, the feature is disabled)')
    parser.add_argument( '--mmcachedir', action=EnvDefault, envvar='MAXMIND_CACHE_DIRECTORY', default='./data', help='directory to store maxmind database in')

    return parser.parse_args()



def main() -> bool:
    args=parse_args()
    logging.basicConfig(level=args.loglevel.upper())
    log.info(f'Starting with args {vars(args)}')

    metrics = build_prometheus_metrics(args.namespace)
    prometheus_client.start_http_server(addr=args.address, port=args.port)

    log.info(f'listing on {args.address}:{args.port}')

    cleanExit = True
    if args.mmlicense and args.mmedition:
        import maxminddb
        log.info('Geoip lookup enabled')
        database_path = prepare_maxmind_database(args.mmlicense, args.mmedition, args.mmcachedir)
        with maxminddb.open_database(database_path.as_posix()) as database:
            cleanExit = collect_metrics(*metrics, update_interval=args.update, geoip_db=database)
    else:
        log.info('Geoip lookup disabled')
        cleanExit = collect_metrics(*metrics, update_interval=args.update)
    return cleanExit


def build_prometheus_metrics(namespace:str):
    """Returns all prometheus metric objects."""
    return (
        DictGauge(
            'chains',
            'Number of chains in nftables ruleset',
            namespace=namespace,
        ),
        DictGauge(
            'rules',
            'Number of rules in nftables ruleset',
            namespace=namespace,
        ),
        DictCounter(
            'counter_bytes',
            'Byte value of named nftables counters',
            labelnames=('family', 'table', 'name'),
            namespace=namespace,
            unit='bytes'
        ),
        DictCounter(
            'counter_packets',
            'Packet value of named nftables counters',
            labelnames=('family', 'table', 'name'),
            namespace=namespace,
            unit='packets'
        ),
        DictGauge(
            'map_elements',
            'Element count of named nftables maps',
            labelnames=('family', 'table', 'name', 'type', 'country'),
            namespace=namespace,
        ),
        DictGauge(
            'meter_elements',
            'Element count of named nftables meters',
            labelnames=('family', 'table', 'name', 'type', 'country'),
            namespace=namespace,
        ),
        DictGauge(
            'set_elements',
            'Element count of named nftables sets',
            labelnames=('family', 'table', 'name', 'type', 'country'),
            namespace=namespace,
        ),
    )


def collect_metrics(chains, rules, counter_bytes, counter_packets, map_elements, meter_elements, set_elements, update_interval, geoip_db=None) -> bool:
    """Loops forever and periodically fetches data from nftables to update prometheus metrics."""
    log.info('Startup complete')
    try:
        while True:
            log.debug('Collecting metrics')
            start = time.time()

            nft_rules=fetch_nftables('ruleset', 'rule')
            rules.set(len(nft_rules))

            commented_rules=[item for item in nft_rules if 'comment' in item.keys()]
            if len(commented_rules) > 0:
                log.debug(f"Iterating over {len(commented_rules)} rules with comments")
                for item in commented_rules:
                    log.debug(f"  {item['comment']}")
                    if not 'counter' in item['expr'][1].keys():
                        log.warning(f'Rule with comment "{item["comment"]}" does not specify a counter and cannot be used.')
                    else:
                        counter_bytes.labels(item).set(item['expr'][1]['counter']['bytes'])
                        counter_packets.labels(item).set(item['expr'][1]['counter']['packets'])

            chains.set(len(fetch_nftables('ruleset', 'chain')))

            # Process explicitly declared nftables objects (counters, maps, ...)
            for item in fetch_nftables('counters', 'counter'):
                counter_bytes.labels(item).set(item['bytes'])
                counter_packets.labels(item).set(item['packets'])
            map_elements.reset()
            for item in fetch_nftables('maps', 'map'):
                for labels, value in annotate_elements_with_country(item, geoip_db):
                    map_elements.labels(labels).set(value)
            meter_elements.reset()
            for item in fetch_nftables('meters', 'meter'):
                for labels, value in annotate_elements_with_country(item, geoip_db):
                    meter_elements.labels(labels).set(value)
            set_elements.reset()
            for item in fetch_nftables('sets', 'set'):
                for labels, value in annotate_elements_with_country(item, geoip_db):
                    set_elements.labels(labels).set(value)

            log.debug(f'Collected metrics in {time.time() - start}s')
            time.sleep(update_interval)
    except subprocess.CalledProcessError as e:
        log.error(f'Execution error running \"{" ".join(e.cmd)}\": {e.stderr}')
        return False
    except KeyboardInterrupt:
        log.info('Aborting query collection due to keyboard interrupt.')
        return True


def fetch_nftables(query_name, type_name):
    """ Uses nft command line tool to fetch objects from nftables.

            nftables   ALL=(root)    NOPASSWD:/usr/sbin/nft --json list *

        (or similar)
    """
    log.debug(f'Fetching nftables {query_name}')
    cmd=('nft', '--json', 'list', query_name)
    log.debug(f"Running {' '.join(cmd)}")
    process = subprocess.run(
        cmd,
        capture_output=True,
        check=True,
        text=True,
    )
    data = json.loads(process.stdout)
    version = data['nftables'][0]['metainfo']['json_schema_version']
    if version != 1:
        raise RuntimeError(f'nftables json schema v{version} is not supported')
    if query_name in [ 'sets', 'meters', 'maps' ] and len(data['nftables'][1:]) > 0:
        log.debug(f"Iterating over {len(data['nftables'][1:])} {query_name}")
        for item in data['nftables'][1:]:
            log.debug(f"  {item[type_name]['name']}")
            cmd=('nft', '--json', 'list', type_name, item[type_name]['family'], item[type_name]['table'], item[type_name]['name'])
            log.debug(f"  Running {' '.join(cmd)}")
            process = subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                text=True,
            )
            item_data = json.loads(process.stdout)
            if 'elem' in item_data['nftables'][1][type_name]:
                item[type_name]['elem'] = item_data['nftables'][1][type_name]['elem']
    return [
        item[type_name]
        for item in data['nftables'][1:]
        if type_name in item
    ]

def annotate_elements_with_country(item, geoip_db):
    """Takes a nftables map, meter or set object and adds country code information to each ip address element."""
    elements = item.get('elem', ())
    if geoip_db and item.get('type') in ('ipv4_addr', 'ipv6_addr'):
        result = defaultdict(int)
        for element in elements:
            if isinstance(element, str):
                country = lookup_ip_country(element, geoip_db)
                result[country] += 1
            elif isinstance(element, dict):
                country = lookup_ip_country(element['elem']['val'], geoip_db)
                result[country] += 1
            else:
                log.debug(f'Got element of unexpected type {element.__class__.__name__} with {item=}')
        for country, value in result.items():
            yield dict(item, country=country), value
    else:
        yield dict(item, country=''), len(elements)


def lookup_ip_country(address, database):
    """Returns the country code for a given ip address."""
    info = database.get(address)
    try:
        return info['country']['iso_code']
    except Exception:
        return ''


def retry(n=2, exceptions=Exception):
    """A function decorator that executes the wrapped function up to n + 1 times if it throws an exception."""
    def decorator(callback):
        def wrapper(*args, **kwargs):
            for _ in range(n):
                try:
                    return callback(*args, **kwargs)
                except exceptions as e:
                    logging.warning(f'retrying function {callback.__name__} because it raised {e.__class__.__name__}: {e}')
                    pass
            return callback(*args, **kwargs)

        return wrapper

    return decorator


def prepare_maxmind_database(license_key, database_edition, storage_dir):
    """Downloads, extracts and caches a maxmind geoip database for offline use."""
    checksum = download_maxmind_database_checksum(license_key, database_edition)
    archive_path = download_maxmind_database_archive(license_key, database_edition, storage_dir, checksum)
    database_path = extract_maxmind_database_archive(database_edition, storage_dir, archive_path)
    return database_path


@retry(exceptions=urllib.error.URLError)
def download_maxmind_database_checksum(license_key, database_edition):
    """Fetches the sha256 checksum for a maxmind database."""
    checksum_url = f'https://download.maxmind.com/app/geoip_download?edition_id={database_edition}&license_key={license_key}&suffix=tar.gz.sha256'
    with urllib.request.urlopen(checksum_url) as response:
        words = response.readline().split(maxsplit=1)
        checksum = words[0].decode()
    log.debug(f'Database checksum {checksum}')
    return checksum


@retry(exceptions=(urllib.error.URLError, RuntimeError))
def download_maxmind_database_archive(license_key, database_edition, storage_dir, checksum):
    """Downloads a maxmind database archive and validates its checksum."""
    archive_path = storage_dir/f'{database_edition}.tar.gz'
    if not archive_path.exists() or not verify_file_checksum(archive_path, checksum):
        log.info('Downloading maxmind geoip database')
        database_url = f'https://download.maxmind.com/app/geoip_download?edition_id={database_edition}&license_key={license_key}&suffix=tar.gz'
        urllib.request.urlretrieve(database_url, filename=archive_path)
    if not verify_file_checksum(archive_path, checksum):
        raise RuntimeError('maxmind database checksum verification failed')
    return archive_path


def extract_maxmind_database_archive(database_edition, storage_dir, archive_path):
    """Unpacks a maxmind database archive."""
    storage_dir.mkdir(exist_ok=True)
    with tarfile.open(archive_path, 'r') as archive:
        archive.extractall(storage_dir)
    database_path = last(storage_dir.glob(f'{database_edition}_*/{database_edition}.mmdb'))
    log.info(f'Maxmind database stored at {database_path}')
    return database_path


def verify_file_checksum(path, expected_checksum):
    """Verifies the sha256 checksum of a file."""
    actual_checksum = calculate_file_checksum(path)
    return actual_checksum == expected_checksum


def calculate_file_checksum(path):
    """Calculates the sha256 checksum of a file."""
    # thanks to https://stackoverflow.com/a/3431838
    checksum = hashlib.sha256()
    with open(path, 'rb') as file:
        for chunk in iter(lambda: file.read(4096), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def last(iterable):
    """Returns the last element of an iterable."""
    return deque(iterable, maxlen=1).pop()


def _filter_labels(data, labelnames):
    return {
        key: value
        for key, value in data.items()
        if key in labelnames
    }


def _reset_labels(self):
    for metric in self.collect():
        for sample in metric.samples:
            self.labels(sample.labels).set(0)


class DictGauge(prometheus_client.Gauge):
    """Subclass of prometheus_client.Gauge with automatic label filtering."""
    def labels(self, data):
        return super().labels(**_filter_labels(data, self._labelnames))

    def reset(self):
        _reset_labels(self)


class DictCounter(prometheus_client.Counter):
    def labels(self, data):
        filtered_data = {
            key: value
            for key, value in data.items()
            if key in self._labelnames
        }
        # If there is no name than there must be a comment
        if not 'name' in filtered_data.keys():
            filtered_data['name'] = data['comment']
        return super().labels(**filtered_data)

    def set(self, data):
        self._value.set(data)

    def reset(self):
        _reset_labels(self)


if __name__ == '__main__':
    try:
        if not main():
            sys.exit(1)
    except KeyboardInterrupt:
        log.info('Terminating on interrupt signal.')
