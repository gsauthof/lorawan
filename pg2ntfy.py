#!/usr/bin/env python3


# pg2ntfy - forward Postgresql notifications to a ntfy.sh instance
#
# SPDX-FileCopyrightText: © 2023 Georg Sauthoff <mail@gms.tf>
# SPDX-License-Identifier: GPL-3.0-or-later


import configargparse
import httpx
import psycopg
import signal
import sys
import systemd.daemon

prefix = '/usr'
prog   = 'pg2ntfy'

def parse_args():
    p = configargparse.ArgParser(
            auto_env_var_prefix=prog + '_',
            default_config_files=[f'{prefix}/lib/{prog}/config.ini',
                f'/etc/{prog}.ini', f'~/.config/{prog}.ini'])
    p.add('-c', '--config', is_config_file=True,
          help='config file')
    p.add('--channel', required=True,
          help='Postgres NOTIFY channel to LISTEN to and forward')
    p.add('--db', '-d', default='dbname=metricsdb',
          help='PostgreSQL metrics database URL (default: %(default)s)')
    p.add('--ntfy', default='https://ntfy.sh',
          help='ntfy server (default: %(default)s)')
    p.add('--systemd', action='store_true',
          help='notify systemd during startup')
    p.add('--topic', required=True, help='Ntfy topic to post to')
    args = p.parse_args()
    return args


def on_sigterm(sig, frm):
    raise KeyboardInterrupt()


def mainP():
    signal.signal(signal.SIGTERM, on_sigterm)
    args = parse_args()

    db = psycopg.connect(args.db, autocommit=True)

    db.execute(f'LISTEN {args.channel}')

    if args.systemd:
        systemd.daemon.notify('READY=1')

    xs = db.notifies()
    for x in xs:
        httpx.post(f'https://ntfy.sh/{args.topic}', content=x.payload)


def main():
    try:
        return mainP()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    sys.exit(main())
