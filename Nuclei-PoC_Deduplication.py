import os
import shutil
import hashlib
import re
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# --- 1. 专业日志配置 ---
# 创建一个 logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 终端处理器，只显示 INFO 等级及以上的消息
c_handler = logging.StreamHandler()
c_handler.setLevel(logging.INFO)
c_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
c_handler.setFormatter(c_formatter)

# 文件处理器，只记录 ERROR 等级的消息
f_handler = logging.FileHandler('processing_errors.log', mode='w', encoding='utf-8')
f_handler.setLevel(logging.ERROR)
f_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
f_handler.setFormatter(f_formatter)

logger.addHandler(c_handler)
logger.addHandler(f_handler)
# --- 日志配置结束 ---

def process_file(file_path, collect_errors_flag, error_dir):
    """
    对单个文件执行所有检查。
    新增了参数来决定是否收集错误文件。
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        result = {
            'path': file_path,
            'filename': os.path.basename(file_path),
            'hash': None,
            'severity': 'unknown',
            'skip_keyword': False
        }

        match_req = re.search(r'^(requests|http):', content, re.MULTILINE)
        if match_req:
            request_block_raw = content[match_req.start():]
            cleaned_lines = [line for line in request_block_raw.splitlines() if not line.strip().startswith('#')]
            condensed_content = re.sub(r'\s+', '', "\n".join(cleaned_lines))
            result['hash'] = hashlib.md5(condensed_content.encode('utf-8')).hexdigest()
        else:
            return None

        match_sev = re.search(r'^\s*severity:\s*(\w+)', content, re.MULTILINE)
        if match_sev:
            result['severity'] = match_sev.group(1).lower()

        primary_keywords = ['HTTP', 'GET', 'POST', 'PUT', 'BaseURL']
        secondary_keywords = ['/readme.txt', '/style.css']
        for line in content.splitlines():
            if any(p_kw in line for p_kw in primary_keywords) and any(s_kw in line for s_kw in secondary_keywords):
                result['skip_keyword'] = True
                break
        
        return result
        
    except Exception as e:
        logger.error(f"文件 '{file_path}' 处理失败，原因: {e}")
        
        # --- 新增改动 ---
        # 如果用户设置了 --collect-errors 标志，则复制出错的文件
        if collect_errors_flag:
            try:
                error_dest_path = os.path.join(error_dir, os.path.basename(file_path))
                shutil.copy2(file_path, error_dest_path)
            except Exception as copy_e:
                logger.error(f"复制出错文件 '{file_path}' 到 '{error_dir}' 失败: {copy_e}")
        # --- 新增改动结束 ---
                
        return None

def main(args):
    """
    主执行函数
    """
    os.makedirs(args.output, exist_ok=True)
    
    # --- 新增改动 ---
    # 如果设置了收集错误的标志，也创建对应的目录
    error_dir = ""
    if args.collect_errors:
        error_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "error_files")
        os.makedirs(error_dir, exist_ok=True)
        logger.info(f"错误文件收集功能已开启，将保存到 '{error_dir}' 目录。")
    # --- 新增改动结束 ---

    logger.info(f"正在从 '{args.source}' 目录收集文件...")
    all_files = []
    for root, _, files in os.walk(args.source):
        for filename in files:
            if filename.endswith((".yaml", ".yml")):
                all_files.append(os.path.join(root, filename))

    if not all_files:
        logger.warning("未找到任何 .yaml/.yml 文件。")
        return

    logger.info(f"共找到 {len(all_files)} 个 PoC 文件，开始处理...")

    seen_hashes = set()
    stats = {'copied': 0, 'duplicate': 0, 'severity_skipped': 0, 'keyword_skipped': 0, 'error': 0}

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # --- 新增改动 ---
        # 提交任务时，传入新的参数
        future_to_file = {executor.submit(process_file, f, args.collect_errors, error_dir): f for f in all_files}
        # --- 新增改动结束 ---
        
        for future in tqdm(as_completed(future_to_file), total=len(all_files), desc="处理 PoC"):
            result = future.result()

            if not result:
                stats['error'] += 1
                continue

            if result['hash'] in seen_hashes:
                stats['duplicate'] += 1
                continue
            
            if result['severity'] in args.exclude_severity:
                stats['severity_skipped'] += 1
                continue

            if result['skip_keyword']:
                stats['keyword_skipped'] += 1
                continue
            
            seen_hashes.add(result['hash'])
            dest_path = os.path.join(args.output, result['filename'])
            shutil.copy2(result['path'], dest_path)
            stats['copied'] += 1

    logger.info("✨✨✨ 所有阶段处理完毕！ ✨✨✨")
    logger.info(f"最终结果已输出到 '{args.output}' 目录中。")
    logger.info(f"详细错误报告已生成于 'processing_errors.log' 文件。")
    if args.collect_errors:
        logger.info(f"所有处理出错的文件已集中复制到 'error_files' 目录。")
    logger.info(f"--- 统计 ---")
    logger.info(f"✅ 成功复制文件: {stats['copied']}")
    logger.info(f"⏭️  因内容重复跳过: {stats['duplicate']}")
    logger.info(f"🚫 因严重性等级 ('{','.join(args.exclude_severity)}') 跳过: {stats['severity_skipped']}")
    logger.info(f"🗑️  因特定关键字跳过: {stats['keyword_skipped']}")
    logger.info(f"❌ 处理出错文件: {stats['error']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="一个高效、灵活的 Nuclei PoC 三阶段筛选工具。")
    parser.add_argument("-s", "--source", required=True, help="存放原始 PoC 的源目录。")
    parser.add_argument("-o", "--output", required=True, help="存放最终筛选结果的输出目录。")
    parser.add_argument("-es", "--exclude-severity", nargs='+', default=['info'], help="需要排除的严重性等级列表，用空格分隔。 (默认: info)")
    parser.add_argument("-w", "--workers", type=int, default=4, help="用于处理文件的并发线程数。 (默认: 4)")
    # --- 新增改动 ---
    parser.add_argument("--collect-errors", action="store_true", help="如果设置，则将所有处理出错的文件复制到 'error_files' 目录。")
    # --- 新增改动结束 ---
    
    args = parser.parse_args()
    main(args)