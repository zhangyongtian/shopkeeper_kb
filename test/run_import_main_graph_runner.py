from __future__ import annotations

from shopkeeper_kb.logging_config import init_logging
from shopkeeper_kb.agents.import_main_graph_runner import ImportMainGraphRunner


def main() -> None:
    init_logging("INFO")
    state = {"local_file_path": r"/home/roott/work/doc/高性能Linux服务器运维实战.pdf"}
    result = ImportMainGraphRunner.create_and_run(state)
    print(result)


if __name__ == "__main__":
    main()
