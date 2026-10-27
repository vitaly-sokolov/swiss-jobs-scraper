"""``python -m jobscraper <scrape|notify|cleanup|migrate> [args]`` — same as the jobs-* scripts.

Handy for debuggers and IDE launch configs that start a module rather than a script.
"""

import sys

from jobscraper.cli import cleanup_main, migrate_main, notify_main, scrape_main

COMMANDS = {"scrape": scrape_main, "notify": notify_main, "cleanup": cleanup_main, "migrate": migrate_main}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: python -m jobscraper {{{'|'.join(COMMANDS)}}} [args]", file=sys.stderr)
        return 2
    return COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
