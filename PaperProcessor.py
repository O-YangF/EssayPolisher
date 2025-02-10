import argparse
import os
import re
import time
import hashlib #哈希去重
import requests # type: ignore
import pdfplumber # type: ignore
from typing import List, Tuple
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter # type: ignore
from urllib3.util.retry import Retry # type: ignore
from init import get_config # type: ignore
from nltk.tokenize import sent_tokenize # type: ignore

config = get_config()

# 使用配置参数
PDF_DIR = config.PDF_DIR  # PDF 文件保存目录
RESULT_DIR = config.RESULT_DIR  # 分析结果保存目录
SEARCH_DIR = config.SEARCH_DIR  # 论文检索结果保存目录
Path = config.Path  #输入目录路径（包含论文链接文件）
Timeout = config.TIMEOUT  #超时时间

MAX_RETRIES = config.MAX_RETRIES # 最大重试次数
BACKOFF_FACTOR = config.BACKOFF_FACTOR # 超时回退系数
MAX_PDF_PAGES = config.MAX_PDF_PAGES  # 最大解析页数
CHUNK_SIZE = config.CHUNK_SIZE   # 文本分块长度

API_KEY = config.API_KEY  # API 密钥
API_URL = config.API_URL  # API 地址
MODEL_ID = config.MODEL_ID  # 模型 ID



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
        response = requests.get(url, stream=True, timeout=Timeout)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(1024*1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    progress = downloaded / total_size * 100
                    print(f"\r原始PDF文件下载进度: {progress:.1f}%", end='')
        print()
        return True
    except Exception as e:
        print(f"\n下载失败 {url}: {str(e)}")
        return False

def detect_section_change(page) -> bool:
    """检测章节标题变化"""
    # 基于字体特征检测标题（示例实现）
    large_fonts = [char["size"] for char in page.chars if char["size"] > 14]
    if len(large_fonts) > 3:
        return True
    # 基于关键词检测
    text = page.extract_text()
    if re.search(r'\b(Abstract|Introduction|Method|References)\b', text):
        return True
    return False

def detect_section_change(page, content) -> bool:
    """增强章节检测逻辑"""
    # 基于字体特征检测
    large_chars = [c for c in page.chars if c["size"] > 14]
    if len(large_chars) > 5 and any(c["text"].isupper() for c in large_chars):
        return True
    
    # 基于内容模式检测
    section_pattern = r'''
        ^\s*                # 起始空白
        (?:                 
            \d+             # 数字编号
            [\.\s]+         # 分隔符
            [A-Z]{3,}       # 大写标题单词
        |  
            [A-Z]{3,}       # 纯大写标题
        )
        \b
    '''
    return re.search(section_pattern, content, re.X) is not None

def extract_pdf_text(pdf_path: str) -> List[str]:
    """分块提取PDF文本"""
    chunks = []
    current_chunk = []
    current_length = 0
    processed_hashes = set()  # 新增重复内容检测
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages[:MAX_PDF_PAGES]):
                # 增强布局参数配置
                text = page.filter(
                    lambda obj: obj["object_type"] == "char" and obj["size"] > 8
                ).extract_text(
                    layout=True,
                    x_tolerance=2,
                    y_tolerance=3,
                    keep_blank_chars=False
                ) or ""

                # 增强型文本清洗管道
                clean_content = re.sub(r'(?<=\b)([A-Z])\s(?=[A-Z]\b)', r'\1', text)  # 修复大写单词分割
                clean_content = re.sub(r'(\d)\s*-\s*(\d)', r'\1-\2', clean_content)  # 保留数字连字符
                clean_content = re.sub(r'\s([\(\{\[\]\}\)])', r'\1', clean_content)  # 修复括号粘连
                clean_content = re.sub(r'([A-Za-z])\s+(?=\d)', r'\1', clean_content)  # 修复字母数字粘连
                clean_content = re.sub(r'\s{2,}', ' ', clean_content).strip()

                # 新增重复内容检测
                content_hash = hashlib.md5(clean_content.encode()).hexdigest()
                if content_hash in processed_hashes:
                    continue
                processed_hashes.add(content_hash)

                # 增强章节检测
                if detect_section_change(page, clean_content):
                    if current_chunk:
                        chunks.append(' '.join(current_chunk))
                        current_chunk = []
                        current_length = 0
                    chunks.append(clean_content)  # 章节标题独立分块
                    continue

                # 智能分块逻辑
                sentences = sent_tokenize(clean_content)
                for sent in sentences:
                    words = re.findall(r'\b\w+[\-/]?\w*\b|[\(\)\{\}\[\]]', sent)  # 增强单词分割
                    
                    for word in words:
                        estimated_length = current_length + len(word) + 1
                        
                        # 动态分块策略（允许±15%浮动）
                        if estimated_length > CHUNK_SIZE * 1.15:
                            if len(current_chunk) > CHUNK_SIZE * 0.3:
                                chunks.append(' '.join(current_chunk))
                                current_chunk = [word]
                                current_length = len(word)
                            else:
                                current_chunk.append(word)
                                current_length += len(word) + 1
                        else:
                            current_chunk.append(word)
                            current_length += len(word) + 1

                    # 句子完整性保护
                    if current_chunk and current_length > CHUNK_SIZE * 0.8:
                        chunks.append(' '.join(current_chunk))
                        current_chunk = []
                        current_length = 0

        return chunks

    except Exception as e:
        print(f"解析PDF失败 {pdf_path}: {str(e)}")
        return []

def process_chunk(session, chunk: str, url: str, chunk_num: int, total_chunks: int) -> str:
    """处理单个文本块"""
    prompt = f"""作为计算机科学领域资深研究员，请基于以下论文片段进行分析（来源：{url}，当前分块进度：{chunk_num}/{total_chunks}）：
                {chunk[:CHUNK_SIZE]}
                
                【第一步：章节定位】
                请首先判断该片段所属的论文章节（如Abstract/Introduction/Methodology/Experiments/Conclusion等），判断依据包括：
                1. 高频术语特征（如Method部分出现算法名、公式）
                2. 结构特征（如Introduction包含研究背景与问题陈述）
                3. 上下文逻辑（如Experiments包含数据集和指标）
                
                【第二步：定向分析】
                根据章节定位，选择以下对应模板进行深度分析（使用中文Markdown格式）：

                ### [章节类型] 内容分析
                #### 核心要素提取
                - **关键论点**：提炼本段的核心主张（如方法原理、实验结论等）
                - **技术细节**：重要公式/算法（用$$...$$标注）及创新点说明
                - **逻辑作用**：阐明本段在全文中的结构性作用
                
                #### 批判性评估
                - **优势分析**：该方法/结论的3个创新性
                - **潜在问题**：可能存在的2个局限性
                - **验证建议**：提出可操作的验证思路
                
                #### 关联标注
                - 关键结论标注PDF出处（如：见P12 Section 4.2）
                - 专业术语中英对照（如：残差连接, Residual Connection）
                
                【输出要求】
                1. 只分析与当前分块相关的内容，禁止推测未提及信息
                2. 技术细节需关联上下文（如公式说明需解释变量含义）
                3. 争议性观点需标注"需交叉验证"
                """

    try:
        response = session.post(
            url = API_URL,
            json={
                "model": MODEL_ID,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "max_tokens": 16384
            },
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout = Timeout 
        )
        response.raise_for_status()

        print(f"当前进度：{chunk_num}/{total_chunks}")

        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"分块处理失败: {str(e)}")
        return ""

def generate_final_summary(session, chunks: List[str], url: str) -> str:
    """生成最终汇总报告"""
    summary_prompt = f"""作为领域专家，请基于以下分块分析结果合成论文综述报告（论文地址：{url}）：
                        {'-'*40}
                        分块分析结果：
                        {'\n\n'.join(chunks)}
                        {'-'*40}
                        
                        ## 综合报告结构要求
                        ### 1. 研究全景图
                        - **问题三角框架**：
                        | 维度 | 内容 |
                        |------|------|
                        | 领域现状 | 主流方法及技术路线 |
                        | 瓶颈分析 | 现有方法的3个根本性缺陷 |
                        | 本文突破 | 解决问题的关键技术路径 |
                        - **理论贡献**：从方法/理论角度分点说明（标注创新等级：⭐⭐⭐）
                        
                        ### 2. 技术解剖
                        - **创新架构**：用伪代码描述核心算法流程
                        ```python
                        # 示例格式：
                        def core_algorithm(input):
                            # 关键步骤说明
                        ```
                        - **创新点对比**：传统方法 vs 本文方法（表格对比至少3个维度）
                        - **关键公式**：精选2-3个核心公式，说明其物理意义及创新性
                        
                        ### 3. 实验深析
                        - **实验设计合理性**：
                        - 数据集选择的代表性分析
                        - 基线对比的完备性评估
                        - **结果可信度**：
                        - 主实验结果是否支持核心论点
                        - 消融实验的因果证明力度
                        
                        ### 4. 学术影响评估
                        - **理论影响**：可能推动的3个研究方向
                        - **工程价值**：工业界落地的2个潜在场景
                        - **局限性**：方法/实验设计的3个主要缺陷
                        
                        ### 5. 延伸矩阵
                        - **关联研究**：推荐3篇互补性论文（格式：第一作者, 标题, 关联点）
                        - **技术路线图**：预测未来1-3年该方向可能的发展路径
                        
                        【写作规范】
                        1. 使用三级标题体系，确保信息层级清晰
                        2. 所有数据结论必须标注来源（如：据P8实验数据）
                        3. 专业术语首次出现时标注英文（如：自注意力机制, Self-Attention）
                        4. 争议性结论需标注"待验证假设"
                        """

    try:
        response = session.post(
            url = API_URL,
            json={
                "model": MODEL_ID,
                "messages": [{"role": "user", "content": summary_prompt}],
                "temperature": 0.2,
                "max_tokens": 16384
            },
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout = Timeout
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"汇总失败: {str(e)}")
        return "生成完整摘要失败，请查看分块分析结果"

def process_paper(session, filename: str, url: str, result_dir: str):
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
        else:
            print("已成功预处理目标论文块，即将调用模型进行处理，该过程与远端api响应速度相关，请稍等")

        # 处理分块
        chunk_results = []
        for idx, chunk in enumerate(text_chunks, 1):
            result = process_chunk(session, chunk, url, idx, len(text_chunks))
            chunk_results.append(result)
            # print(chunk+"\n\n")
            time.sleep(1)  # 请求间隔

        # 生成汇总
        final_summary = generate_final_summary(session, chunk_results, url)

        # 保存结果
        md_filename = os.path.splitext(filename)[0] + ".md"
        output_part_path = os.path.join(result_dir, os.path.basename("/part"))
        os.makedirs(output_part_path, exist_ok=True)
        output_part_path = os.path.join(output_part_path, os.path.basename(md_filename))

        output_sum_path = os.path.join(result_dir, os.path.basename("/sum"))
        os.makedirs(output_sum_path, exist_ok=True)
        output_sum_path = os.path.join(output_sum_path, os.path.basename(md_filename))
        
        #保存分块结果
        with open(output_part_path, "w", encoding="utf-8") as f:
            f.write(f"# 论文分块分析报告\n\n")
            f.write(f"## 原文信息\n- 地址: [{url}]({url})\n")
            f.write(f"## 分块分析\n")
            for i, res in enumerate(chunk_results, 1):
                f.write(f"\n### 片段 {i}\n{res}\n")
        
        #保存全文结果
        with open(output_sum_path, "w", encoding="utf-8") as f:
            f.write(f"# 论文全文分析报告\n\n")
            f.write(f"## 原文信息\n- 地址: [{url}]({url})\n")
            f.write(f"\n## \n{final_summary}")
            
        print(f"成功保存分块处理结果至{output_part_path}\n成功保存全文分析结果至{output_sum_path}")

    except Exception as e:
        print(f"处理失败: {str(e)}")

if __name__ == "__main__":    
    # 初始化环境
    os.makedirs(PDF_DIR, exist_ok=True)
    result_dir = os.path.join(RESULT_DIR, os.path.basename(Path.rstrip("/\\")))
    os.makedirs(result_dir, exist_ok=True)

    # 创建会话
    session = setup_requests_session()

    # 处理文件
    files = [f for f in os.listdir(Path) if f.endswith(".txt")]
    for idx, filename in enumerate(files, 1):
        print(f"\n即将处理第{idx}/{len(files)}篇目标论文: {filename}")  
        with open(os.path.join(Path, filename), "r", encoding="utf-8") as f:
            url = f.readline().strip()
            process_paper(session, filename, url, result_dir)