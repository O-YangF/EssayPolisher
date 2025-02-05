import os
import json
import argparse

class Config:
    def __init__(self):
        # 系统路径配置
        self.PDF_DIR = "./pdfs"  # PDF 文件保存目录
        self.RESULT_DIR = "./result"  # 分析结果保存目录
        self.SEARCH_DIR = "./res"  # 论文检索结果保存目录
        self.Path = "./default"   #输入目录默认路径（包含论文链接文件）

        # 网络请求配置
        self.MAX_RETRIES = 10  # 最大重试次数
        self.BACKOFF_FACTOR = 2  # 重试时的时间回退系数

        # PDF 解析配置
        self.MAX_PDF_PAGES = 10  # 提取文本的最大页数
        self.CHUNK_SIZE = 10000  # 文本分块长度

        # API 配置
        self.API_KEY = "sk-uywzdvptgwqpouigeqtqropwllunxigdspbybwpvaaxhyxfg"  # API 密钥
        self.API_URL = "https://api.siliconflow.cn/v1/chat/completions"  # API 地址
        self.MODEL_ID = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"  # 模型 ID

        # 论文检索配置
        self.DEFAULT_KEYWORD = "TTA"  # 默认检索关键词
        self.DEFAULT_SEARCH_COUNT = 10  # 默认检索返回论文数量

        # 其他配置
        self.LOG_LEVEL = "INFO"  # 日志级别
        self.SHOW_PROGRESS = True  # 是否显示下载进度条

    def __repr__(self):
        return json.dumps(self.__dict__, indent=4)

def get_config():
    # 初始化配置
    config = Config()

    # 使用命令行参数覆盖配置
    parser = argparse.ArgumentParser(description='ArXiv 论文分析与检索工具')
    
    # 检索器的参数
    parser.add_argument('--path', type=str, help='输入目录路径（包含论文链接文件）')

    # 优化器的参数
    parser.add_argument('--key', type=str, help='检索关键词')
    parser.add_argument('--n', type=int, help='返回论文数量')
    parser.add_argument('--name', type=str, default="default", help='输出目录名')

    # 解析命令行参数
    args = parser.parse_args()

    # 更新配置
    if args.path:
        config.Path = args.path
    if args.key:
        config.DEFAULT_KEYWORD = args.key
    if args.n:
        config.DEFAULT_SEARCH_COUNT = args.n
    if args.name:
        config.SEARCH_DIR = os.path.join(config.SEARCH_DIR, args.name)

    return config