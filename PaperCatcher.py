from langchain.retrievers import ArxivRetriever  # type: ignore
from langchain.schema import Document  # type: ignore
from typing import List
from datetime import datetime
import argparse
import os

def query_academic_papers(
    keyword: str,
    n: int = 10,
    load_max_docs: int = 100,
    get_full_document: bool = False
) -> List[dict]:
    """
    查询指定数量的学术论文
    
    :param keyword: 搜索关键词
    :param load_max_docs: 最大加载文档数(默认10)
    :param get_full_document: 是否加载完整文本(默认False)
    :return: 包含论文元数据和内容的字典列表
    """
    # #判断是否需要完全完整的论文
    # if get_full_document == True:
    #     papers = query_academic_papers(keyword=keyword, n=n)
    #     # 遍历列表，提取 Entry ID 并存入字典
    #     entry_ids_dict = {}
    #     for paper in papers:
    #         entry_id = paper.metadata.get("Entry ID")
    #         entry_ids_dict["Entry_ID"] = entry_id

    # 初始化检索器
    retriever = ArxivRetriever(
        load_max_docs=load_max_docs,
        top_k_results = n,
        get_full_documents=get_full_document,
        # doc_content_chars_max=20000  # 控制单篇内容长度
    )
    
    try:
        # 执行检索（显式指定返回数量）
        results = retriever.invoke(
            keyword
        )
        # if get_full_document == True:
        #     for result in results:
        #         result["Entry_ID"] = entry_ids_dict["Entry_ID"]
        
        return results
    
    except Exception as e:
        print(f"检索时发生错误: {str(e)}")
        return []

def save_paper_content(paper: Document, output_dir: str) -> None:
    """
    将单篇论文的内容保存到文件中，文件名格式为“时间+fileurl+论文题目”
    """
    # 提取论文的发布时间
    published_date = paper.metadata.get('Published', 'Unknown')  
    
    # 提取论文题目，用于文件名（去除非法字符）
    title = paper.metadata.get('Title', 'Untitled').strip()
    title = "".join([c for c in title if c.isalnum() or c in (' ', '.', '_', '-')]).replace(' ', '_')
        
    fileurl = paper.metadata.get('Entry ID')
    
    # 生成文件名
    file_name = f"{published_date}-{title}.txt"
    
    # 生成输出路径
    output_path = os.path.join(output_dir, file_name)
    
    # 提取论文内容
    content = [
        f"{fileurl}",
        f"Content: {paper.page_content if paper.page_content else 'No full text available'}",
    ]
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(content))
    
    print(f"成功保存论文到: {output_path}")

def main():
    # 配置命令行参数
    parser = argparse.ArgumentParser(description='arXiv论文检索工具')
    parser.add_argument('--key', type=str, default="TTA", 
                       help='搜索关键词（默认：TTA）')
    parser.add_argument('--name', type=str, default="default",
                       help='输出目录（默认：default）')
    parser.add_argument('--n', type=int, default=10,
                       help='返回论文数量（默认：10）')
    args = parser.parse_args()
    
    args.name = "res/"+args.name
    # 确保输出目录存在
    os.makedirs(args.name, exist_ok=True)
    
    # 执行检索
    papers = query_academic_papers(keyword=args.key, n=args.n)
    
    # 保存每篇论文的内容
    if not papers:
        print("未检索到有效论文结果")
        return
    
    for i, paper in enumerate(papers, 1):
        save_paper_content(paper, args.name)

if __name__ == "__main__":
    main()