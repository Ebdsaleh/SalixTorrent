"""Console entry point used by the frozen SalixTorrentCLI executable."""

import sys

from main import main


if __name__ == "__main__":
    if "--cli" not in sys.argv[1:]:
        sys.argv.insert(1, "--cli")
    main()
