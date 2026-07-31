"""
查询流程节点基类
定义统一的节点接口规范，提供通用功能
"""

from abc import ABC, abstractmethod
from shopkeeper_kb import logging_config as log
from shopkeeper_kb.workflows.state import ImportGraphState

class NodeBase(ABC):
    name: str = "node_base" # 节点名称
    
    def __init__(self):
        if self.name == "node_base":
            raise ValueError(f"子类 {self.__class__.__name__} 必须实现 name 属性")
        
    def __call__(self, state: ImportGraphState) -> ImportGraphState:
        """
        节点调用方法
        定义节点的执行逻辑，返回更新后的状态
        """
        try:
            log.info(f"-- {self.name} -- 开始执行")
            state = self.process(state)
            log.info(f"-- {self.name} -- 执行完成")
            return state
        except Exception as e:
            log.error(f"-- {self.name} 执行异常: {e}")
            raise
        
    @abstractmethod
    def process(self, state: ImportGraphState) -> ImportGraphState:
        """
        节点处理方法
        定义节点的具体执行逻辑，返回更新后的状态
        """
        pass
