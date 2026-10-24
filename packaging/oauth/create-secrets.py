#!/usr/bin/env python3
"""Parent/operator only: create protected secret files; never start a service."""
import argparse
import getpass
import os
from pathlib import Path
import secrets
import stat
import sys
from render import absolute_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(2, 'BLOCKED: root required to assign container UID 1000 secret ownership\n')
    try:
        target = Path(absolute_path(args.directory))
        if target.exists():
            raise ValueError('Refusing existing secret directory (never rotate a live DB password this way)')
        # Enter through a controlling TTY, not command line, environment, chat or logs.
        if not sys.stdin.isatty():
            raise ValueError('Interactive terminal required for bootstrap credential entry')
        bootstrap = getpass.getpass('Bootstrap admin password (store in your password manager): ')
        confirm = getpass.getpass('Confirm bootstrap admin password: ')
        if bootstrap != confirm or len(bootstrap) < 24 or not bootstrap.isascii() or not bootstrap.isalnum():
            raise ValueError('Use matching password-manager-generated 24+ ASCII alphanumeric characters')
        # Alphanumeric constraint avoids Keycloak property-expression interpolation.
        target.mkdir(mode=0o700, parents=False)
        if target.is_symlink() or stat.S_IMODE(target.stat().st_mode) != 0o700:
            raise ValueError('Unsafe secret directory permissions')
        values = {'bootstrap_password': bootstrap,
                  'database_password': secrets.token_hex(32),
                  'introspection_secret': secrets.token_hex(32)}
        for name, value in values.items():
            fd = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(value + '\n')
                os.fchown(stream.fileno(), 1000, 0)
        print('Protected files created; no secret values printed. Deployment NOT RUN.')
    except (OSError, ValueError) as error:
        parser.exit(2, f'BLOCKED: {error}\n')


if __name__ == '__main__':
    main()
