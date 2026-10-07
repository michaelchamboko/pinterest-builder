"""Launch the vendor-documented MCP bridge without putting API keys in argv."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('imagekit', 'shortio'):
        print('Usage: mcp_bridge.py imagekit|shortio', file=sys.stderr)
        return 2
    npx = shutil.which('npx.cmd' if os.name == 'nt' else 'npx')
    if not npx:
        print('Node.js/npx is required for the MCP connections.', file=sys.stderr)
        return 1
    environment = dict(os.environ)
    if sys.argv[1] == 'shortio':
        from pinterest_services import load_env
        local_key = load_env(ROOT / '.env.local').get('SHORTIO_API_KEY', '')
        if local_key:
            environment['SHORTIO_API_KEY'] = local_key
        if not environment.get('SHORTIO_API_KEY', '').strip():
            print('Set SHORTIO_API_KEY in the project .env.local; never paste it into chat.', file=sys.stderr)
            return 1
        arguments = ['https://ai-assistant.short.io/mcp', '--header', 'Authorization:${SHORTIO_API_KEY}']
    else:
        from pinterest_services import load_env
        local_key = load_env(ROOT / '.env.local').get('IMAGEKIT_PRIVATE_KEY', '')
        if local_key:
            environment['IMAGEKIT_PRIVATE_KEY'] = local_key
        if not environment.get('IMAGEKIT_PRIVATE_KEY', '').strip():
            print('Set IMAGEKIT_PRIVATE_KEY in the project .env.local.', file=sys.stderr)
            return 1
        arguments = []
    try:
        package = 'mcp-remote@0.14.2' if sys.argv[1] == 'shortio' else '@imagekit/api-mcp@7.11.0'
        return subprocess.call([npx, '-y', package, *arguments], env=environment,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except OSError:
        print('Could not start the MCP bridge. Check Node.js and network access.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
