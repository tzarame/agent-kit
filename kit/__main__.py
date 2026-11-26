"""__main__.py - the kit's command: python3 -I kit/__main__.py COMMAND. -I leaves the script's folder and the current
folder out of the imports, so the kit's repository is put in front of them here."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kit import cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(cli.main(sys.argv[1:]))
