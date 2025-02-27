# Prometheus Nftables Exporter

A Prometheus Exporter that exposes metrics from [nftables](https://nftables.org/projects/nftables/index.html).

**Forked from dadevel/prometheus-nftables-exporter**

The upstream has been archived and newer nftables command-line clients introduced a breaking change by not listing elements when listing all sets, maps, or meters. This fork simply iterates through each to resolve.


The exposed metrics consist of

1. The size of certain nftables objects (ruleset, chains, maps, sets)
2. Packet and byte values of named counters
3. Packet and byte values of rules that use a counter and additionally specify a comment. The comment is used as a name then.

Care must be taken that counter-names and comments are unique within the scope of a table. I.e. equality between a counter name and a comment will lead to wrong results. As will two identical comments or two identical counter-names. Whitespace in names should also be avoided for practical purpose.

While it is convenient to expose packet/byte metrics just by adding a comment, this approach does not allow to sum up data originating from multiple rules. Named counters must be used in that case.

![Example Grafana Dashboard Screenshot](./images/grafana.png)

## Building

The project conains a `Makefile` which documents build-related procedures like creating an executable or a docker image. Use `make` (without arguments) to see its help.

## Running

### ... using Docker

First, create the docker image.

~~~ bash
$ make image
...
~~~

Then run the docker image. It does not make much sense to scrape the nftables rules inside the container as there are none. You usually want to scrape the metrics of the docker host (i.e. the system you run the docker command on). To do this, you must tell docker to use the hosts network namespace.

In addition, the exporter obtains its data by running the nftables `nft` executable. That requires the `net_admin` capability.

~~~ bash
$ docker run --rm --cap-drop all --cap-add net_admin --network host nftables-exporter
INFO:nftables-exporter:Starting with args {'address': '0.0.0.0', 'port': 9630, 'update': 60, 'namespace': 'nftables', 'loglevel': 'info', 'mmlicense': None, 'mmedition': 'GeoLite2-Country', 'mmcachedir': './data'}
...
~~~

And test it. This might look confusing. But as a result of using the hosts network namespace, the process port is available on `localhost`.

~~~ bash
$ curl -s http://localhost:9630 | grep nftables
# HELP nftables_chains Number of chains in nftables ruleset
# TYPE nftables_chains gauge
nftables_chains 10.0
...
~~~

### ... not using Docker

Install the dependencies and run the python script. Usually you'll want to setup a virtual environment (aka "venv") for that purpose to not mess up your global python installation:

~~~ bash
$ python3 -m venv .venv
$ . .venv/bin/activate
(.venv) $ pip3 install -r ./requirements.txt
...
(.venv) $ python3 ./nftables-exporter.py -h
usage: nftables-exporter.py ...
~~~

The exporter calls the `nft` command to obtain nftables data. `nft` requires the `cap_net_admin` capability to do so. You could use sudo to run as root and thereby obtain that capability. Unfortunately that interferes with the virtualenv setup as that is not inherited to the new process that sudo creates.

One way around that is to perform your development with the root user directly but that cannot be recommended of course. Unfortunately I don't know any other way :-/.

## Annotating Geolocation
nftables-exporter can annotate ip addresses in nftables maps, meters and sets with a country code. You can use this for example with the [Grafana Worldmap Panel](https://github.com/grafana/worldmap-panel). Unfortunately you have provide a (free) MaxMind license key. See [here](https://dev.maxmind.com/geoip/geoip2/geolite2/) for more information.

~~~ bash
docker run --rm --cap-drop all --cap-add net_admin --network host ststefa/nftables-exporter --mmlicense INSERT_YOUR_KEY_HERE
~~~

## Configure

The exporter can be configured using arguments and/or environment variables (args take precedence). Pythons argparse module is used so you can get a list of available args/vars by specifying `-h` or `--help` on the commandline.

~~~ bash
(.venv) $ ./nftables-exporter.py -h
...
optional arguments:
  -h, --help            show this help message and exit
  -a ADDRESS, --address ADDRESS
                        listen address (default: 0.0.0.0) [envvar: NFTABLES_EXPORTER_ADDRESS]
  -p PORT, --port PORT  listen port (default: 9630) [envvar: NFTABLES_EXPORTER_PORT]
  -u UPDATE, --update UPDATE
                        update interval in seconds (default: 60) [envvar: NFTABLES_EXPORTER_UPDATE_PERIOD]
  -n NAMESPACE, --namespace NAMESPACE
                        all metrics are prefixed with the namespace (default: nftables) [envvar: NFTABLES_EXPORTER_NAMESPACE]
  -l LOGLEVEL, --loglevel LOGLEVEL
                        one of the log levels from pythons `logging` module (default: info) [envvar: NFTABLES_EXPORTER_LOG_LEVEL]
  --mmlicense MMLICENSE
                        license key for maxmind geoip database (optional) (default: None) [envvar: MAXMIND_LICENSE_KEY]
  --mmedition MMEDITION
                        maxmind database edition (default: GeoLite2-Country) [envvar: MAXMIND_DATABASE_EDITION]
  --mmcachedir MMCACHEDIR
                        directory to store maxmind database in (default: ./data) [envvar: MAXMIND_CACHE_DIRECTORY]
~~~

## Example

Firewall ruleset:

~~~ bash
$ nft list ruleset
table inet filter {
  counter http-allowed {
  }

  counter http-denied {
  }

  chain input {
    type filter hook input priority 0
    policy drop
    tcp dport { 80, 443 } meter http-limit { ip saddr limit rate over 16 mbytes/second } counter name http-denied drop
    tcp dport { 80, 443 } meter http6-limit { ip6 saddr limit rate over 16 mbytes/second } counter name http-denied drop
    tcp dport { 80, 443 } counter name http-allowed accept
    tcp dport 22 counter accept comment "ssh_in"
  }
}
~~~

Resulting metrics:

~~~ bash
$ curl -s http://localhost:9630 | grep ^nftables
nftables_counter_bytes_total{family="inet", name="http-allowed", table="filter"} 90576
nftables_counter_packets_total{family="inet", name="http-allowed", table="filter"} 783
nftables_counter_bytes_total{family="inet", name="http-denied", table="filter"} 936
nftables_counter_packets_total{family="inet", name="http-denied", table="filter"} 13
nftables_counter_bytes_total{family="inet", name="ssh_in", table="filter"} 756
nftables_counter_packets_total{family="inet", name="ssh_in", table="filter"} 8
nftables_meter_elements{family="ip", name="http-limit", table="filter", type="ipv4_addr", country="US"} 7
nftables_meter_elements{family="ip", name="http-limit", table="filter", type="ipv4_addr", country="DE"} 3
nftables_meter_elements{family="ip", name="http-limit", table="filter", type="ipv4_addr", country=""} 2
nftables_meter_elements{family="ip6", name="http6-limit", table="filter", type="ipv6_addr", country="US"} 2
~~~

**Notice:** Since v2.0.0 `nftables_counter_bytes` and `nftables_counter_packets` are proper Prometheus counters and therefore got a `_total` suffix.

## Building an Executable

If the exporter is to be deployed to a large set of machines (which commonly occurs with exporters), then the runtime dependency on python or docker might become a problem (your milage may vary).

Luckily, not only golang code can be turned into a standalone executable. Python offers a tool called `pyinstaller` for that purpose.

To compile the exporter into a standalone executable:

~~~ bash
(.venv) $ pip3 install pyinstaller
...
(.venv) $ pyinstaller --onefile nftables-exporter.py
...
~~~

This will result in a ready-to-run `dist/nftables-exporter` executable which can be used on other machines without installing a python interpreter there.

As a drawback, `pyinstaller` does not offer cross-compilation like golang. The executable will thus only work on targets with the same os/arch combination. If multiple os/arch combination must be supported (say, amd64 and arm64) then you'll have to compile the exporter separately on any of these :-/.

Also, note that the executable is still dynamically linked. So care must be taken regarding the base system. However, this should not usually be a problem as the dependencies are quite minimal and broadly available.

~~~ bash
$ ldd dist/nftables-exporter
	linux-vdso.so.1 (0x00007ffd18f4f000)
	libdl.so.2 => /lib/x86_64-linux-gnu/libdl.so.2 (0x00007fe31ec9d000)
	libz.so.1 => /lib/x86_64-linux-gnu/libz.so.1 (0x00007fe31ec80000)
	libpthread.so.0 => /lib/x86_64-linux-gnu/libpthread.so.0 (0x00007fe31ec5e000)
	libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007fe31ea99000)
	/lib64/ld-linux-x86-64.so.2 (0x00007fe31ecac000)
~~~

As an additional step, the exporter can of course be further packaged into a distribution package (e.g. `.deb` or `.rpm`), easing the deployment and management process further.

## Debugging remotely with VScode

I find it very convenient to use VScode on my local Mac while actually developing on a remote Linux system. Mostly as a note to my future self this is how it is set up.

- Connect VScode to your remote machine using the [Remote - SSH](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-ssh)
 extension

- Create a `.vscode/launch.json` to attach remotely to the host `lemon` (obviously an example, substitute with your hostname)

    ~~~ yaml
    {
        "version": "0.2.0",
        "configurations": [
            {
                "name": "Python: Remote Attach",
                "type": "python",
                "request": "attach",
                "connect": {
                    "host": "lemon",
                    "port": 5678
                },
                "pathMappings": [
                    {
                        "localRoot": "${workspaceFolder}",
                        "remoteRoot": "."
                    }
                ],
                "justMyCode": true
            }
        ]
    }
    ~~~

    It's important that the local and remote directories match. If you (like me) like to use multi-folder workspaces then you might have to adjust the `lcoalRoot` to properly point to the folder containing the exporter source.

- On lemon, install debugpy to your virtual env

    ~~~ bash
    (.venv) $ pip3 install debugpy
    ...
    ~~~

- Still on lemon, start the exporter using the debugger

    ~~~ bash
    (.venv) $ python3 -m debugpy --listen 0.0.0.0:5678 --wait-for-client nftables-exporter.py
    ~~~

    Additional wisdom is available from `python3 -m debugpy -h` or its repo at <https://github.com/microsoft/debugpy/>.

- In VsCode, switch to `Run/Debug` view and attach using the configuration created above. You might want to create a breakpoint first ;).
