from shopkeeper_kb import logging_config as log
from langgraph.constants import END
from langgraph.graph import StateGraph

from shopkeeper_kb.workflows.node_pdf_to_md import NodePDFToMD
from shopkeeper_kb.workflows.state import ImportGraphState
from shopkeeper_kb.workflows.node_document_split import NodeDocumentSplit
from shopkeeper_kb.workflows.node_item_name_recognition import NodeItemNameRecognition
from shopkeeper_kb.workflows.node_bge_embedding import NodeBGEEmbedding
from shopkeeper_kb.workflows.node_import_milvus import NodeImportMilvus
from shopkeeper_kb.workflows.node_entry import NodeEntry
from shopkeeper_kb.workflows.node_md_img import NodeMDImg

class ImportMainGraphRunner:
    """
    导入主图运行器：协调节点执行
    """
    def __init__(self):
        self.builder = StateGraph(ImportGraphState)
        self.add_nodes()
        self.add_edges()
        self.graph = self.builder.compile()
        self.builder = None
        
    def add_nodes(self):
        """
        添加节点到状态图
        """
        self.builder.add_node(NodeEntry.name, NodeEntry())
        self.builder.add_node(NodePDFToMD.name, NodePDFToMD())
        self.builder.add_node(NodeMDImg.name, NodeMDImg())
        self.builder.add_node(NodeDocumentSplit.name, NodeDocumentSplit())
        self.builder.add_node(NodeItemNameRecognition.name, NodeItemNameRecognition())
        self.builder.add_node(NodeBGEEmbedding.name, NodeBGEEmbedding())
        self.builder.add_node(NodeImportMilvus.name, NodeImportMilvus())
        
    
    def add_edges(self):
        """
        添加节点之间的边
        """
        self.builder.set_entry_point(NodeEntry.name)
        self.builder.add_conditional_edges(NodeEntry.name, self.after_entry_router,{
            NodePDFToMD.name: NodePDFToMD.name,
            NodeMDImg.name: NodeMDImg.name
        })
        self.builder.add_edge(NodePDFToMD.name, NodeMDImg.name)
        self.builder.add_edge(NodeMDImg.name, NodeDocumentSplit.name)
        self.builder.add_edge(NodeDocumentSplit.name,NodeItemNameRecognition.name)
        self.builder.add_edge(NodeItemNameRecognition.name,NodeBGEEmbedding.name)
        self.builder.add_edge(NodeBGEEmbedding.name,NodeImportMilvus.name)
        self.builder.add_edge(NodeImportMilvus.name,END)
        
    def after_entry_router(self, state: ImportGraphState) -> str:
        """
        入口节点路由函数：根据状态判断后续执行路径
        :param state: 输入状态
        :return: 下一个节点名称
        """
        is_pdf_read_enabled = state.get("is_pdf_read_enabled", False)
        is_md_read_enabled = state.get("is_md_read_enabled", False)
        if is_pdf_read_enabled:
            return NodePDFToMD.name
        elif is_md_read_enabled:
            return NodeMDImg.name
        else:
            return END
        
    def run(self, state: ImportGraphState) -> ImportGraphState:
        """
        运行状态图：根据状态执行节点
        :param state: 输入状态
        :return: 更新后的状态
        """
        result = self.graph.invoke(state)
        return result
    
    @classmethod
    def create_and_run(cls, state: ImportGraphState):
        return cls().run(state)

if __name__ == "__main__":
    log.init_logging("INFO")
    init_state = {
        "local_file_path":r"D:\output\hak180产品安全手册.md",
        "is_pdf_read_enabled": True,
        "is_md_read_enabled": False
    }
    result = ImportMainGraphRunner.create_and_run(init_state)
    print(result)
    
        
        
