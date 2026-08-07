import json

from shopkeeper_kb import logging_config as log
from shopkeeper_kb.workflows.base_node import NodeBase
from shopkeeper_kb.workflows.state import ImportGraphState


class NodeTest(NodeBase):
    name: str = "node_test" # 节点名称

    def process(self, state: ImportGraphState) -> ImportGraphState:
        """
        节点处理方法
        定义节点的具体执行逻辑，返回更新后的状态
        :param state: 输入状态
        :return: 更新后的状态
        """
        log.info(f"-- {self.name} -- 结点开始处理")
        return state

if __name__ == "__main__":
    log.init_logging("INFO")
    node_test = NodeTest()
    state = {"task_id": "123"}
    state = node_test(state)
    state_str = json.dumps(state, indent=4)
    print(state_str)
