from __future__ import annotations

import argparse

from executor.server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Secret-less Python executor")
    sub = parser.add_subparsers(dest="command", required=True)
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=7070)
    serve_parser.add_argument("--workdir", required=True)
    args = parser.parse_args()
    if args.command == "serve":
        if args.host not in {"127.0.0.1", "localhost"}:
            raise SystemExit("executor yalnızca localhost dinler")
        serve(args.host, args.port, args.workdir)


if __name__ == "__main__":
    main()
