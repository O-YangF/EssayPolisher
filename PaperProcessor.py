import argparse
import os
import re
import time
import requests
import pdfplumber
from typing import List, Tuple
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置参数
PDF_DIR = "./pdfs"
MAX_RETRIES = 10 # 最大重试次数
BACKOFF_FACTOR = 2 # 超时回退系数
MAX_PDF_PAGES = 10  # 最大解析页数
CHUNK_SIZE = 10000   # 文本分块长度

def setup_requests_session():
    """配置带重试机制的请求会话"""
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=[502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    return session

def extract_arxiv_id(url: str) -> str:
    """从arXiv URL提取论文ID（兼容版本号）"""
    pattern = r"arxiv\.org/(abs|pdf)/([\d\.v]+)"
    match = re.search(pattern, url)
    if not match:
        raise ValueError(f"无效的arXiv链接: {url}")
    return match.group(2).split('.pdf')[0]

def download_pdf(url: str, save_path: str) -> bool:
    """下载PDF文件到指定路径（带进度显示）"""
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(1024*1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    progress = downloaded / total_size * 100
                    print(f"\r下载进度: {progress:.1f}%", end='')
        print()
        return True
    except Exception as e:
        print(f"\n下载失败 {url}: {str(e)}")
        return False

def extract_pdf_text(pdf_path: str) -> List[str]:
    """分块提取PDF文本"""
    chunks = []
    current_chunk = []
    current_length = 0
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages[:MAX_PDF_PAGES]):
                content = page.extract_text() or ""
                clean_content = re.sub(r'\s+', ' ', content).strip()
                
                words = clean_content.split()
                for word in words:
                    if current_length + len(word) + 1 > CHUNK_SIZE:  # +1 for space
                        chunks.append(' '.join(current_chunk))
                        current_chunk = []
                        current_length = 0
                    current_chunk.append(word)
                    current_length += len(word) + 1
                
                if current_chunk:
                    chunks.append(' '.join(current_chunk))
                    current_chunk = []
                    current_length = 0
                    
        return chunks
    except Exception as e:
        print(f"解析PDF失败 {pdf_path}: {str(e)}")
        return []

def process_chunk(session, api_key: str, chunk: str, url: str, chunk_num: int, total_chunks: int) -> str:
    """处理单个文本块"""
    prompt = f"""请分析论文片段（来自{url}）：
                {chunk[:CHUNK_SIZE]}

                当前进度：{chunk_num}/{total_chunks}
                请提取：
                1. 本段核心观点
                2. 关键技术术语（中英对照）
                3. 重要实验数据
                4. 需要后续验证的内容"""

    try:
        response = session.post(
            url="https://api.siliconflow.cn/v1/chat/completions",
            json={
                "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 4096
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()

        print(f"当前进度：{chunk_num}/{total_chunks}")

        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"分块处理失败: {str(e)}")
        return ""

def generate_final_summary(session, api_key: str, chunks: List[str], url: str) -> str:
    """生成最终汇总报告"""
    summary_prompt = f"""根据以下分析片段汇总论文：
                        论文地址: {url}
                        分析片段:
                        {'-'*40}
                        {'\n\n'.join(chunks)}
                        {'-'*40}

                        请按以下结构组织：
                        ## 核心贡献
                        ## 技术路线
                        ## 实验结果
                        ## 局限性与展望"""

    try:
        response = session.post(
            url="https://api.siliconflow.cn/v1/chat/completions",
            json={
                "model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
                "messages": [{"role": "user", "content": summary_prompt}],
                "temperature": 0.2,
                "max_tokens": 2048
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"汇总失败: {str(e)}")
        return "生成完整摘要失败，请查看分块分析结果"

def process_paper(session, api_key: str, filename: str, url: str, result_dir: str):
    """处理单篇论文"""
    try:
        # 下载PDF
        arxiv_id = extract_arxiv_id(url)
        pdf_path = os.path.join(PDF_DIR, f"{arxiv_id}.pdf")
        
        if not os.path.exists(pdf_path) and not download_pdf(f"https://arxiv.org/pdf/{arxiv_id}.pdf", pdf_path):
            return

        # 分块处理
        text_chunks = extract_pdf_text(pdf_path)
        if not text_chunks:
            print("未提取到有效文本")
            return

        # 处理分块
        chunk_results = []
        for idx, chunk in enumerate(text_chunks, 1):
            result = process_chunk(session, api_key, chunk, url, idx, len(text_chunks))
            chunk_results.append(result)
            time.sleep(1)  # 请求间隔

        # 生成汇总
        final_summary = generate_final_summary(session, api_key, chunk_results, url)

        # 保存结果
        md_filename = os.path.splitext(filename)[0] + ".md"
        output_path = os.path.join(result_dir, md_filename)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# 论文分析报告\n\n")
            f.write(f"## 原文信息\n- 地址: [{url}]({url})\n")
            f.write(f"## 分块分析\n")
            for i, res in enumerate(chunk_results, 1):
                f.write(f"\n### 片段 {i}\n{res}\n")
            f.write(f"\n## 最终汇总\n{final_summary}")
            
        print(f"成功保存: {output_path}")

    except Exception as e:
        print(f"处理失败: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='arXiv论文分析工具')
    parser.add_argument('--path', required=True, help='输入目录路径')
    args = parser.parse_args()

    API_KEY = ""
    
    # 初始化环境
    os.makedirs(PDF_DIR, exist_ok=True)
    result_dir = os.path.join("./result", os.path.basename(args.path.rstrip("/\\")))
    os.makedirs(result_dir, exist_ok=True)

    # 创建会话
    session = setup_requests_session()

    # 处理文件
    files = [f for f in os.listdir(args.path) if f.endswith(".txt")]
    for filename in files:
        print(f"\n处理文件: {filename}")
        with open(os.path.join(args.path, filename), "r", encoding="utf-8") as f:
            url = f.readline().strip()
            process_paper(session, API_KEY, filename, url, result_dir)