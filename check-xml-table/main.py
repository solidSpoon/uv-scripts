# -*- coding: utf-8 -*-
import os
import re
import logging
from collections import defaultdict
import shutil # For potential backup functionality

# 配置日志记录器 (中文)
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logging.addLevelName(logging.INFO, "信息")
logging.addLevelName(logging.WARNING, "警告")
logging.addLevelName(logging.ERROR, "错误")
logging.addLevelName(logging.DEBUG, "调试")

# --- 常量 ---
PREFIX = "ced_todo_" # 定义要添加的前缀

# --- 正则表达式创建函数 ---

# 查找表别名 (保持不变)
def create_alias_pattern(table_name):
    pattern = r'(?:FROM|JOIN|UPDATE)\s+' + re.escape(table_name) + r'\s+(?:AS\s+)?(\b\w+\b)'
    pattern_alt = r'([,\s])' + re.escape(table_name) + r'\s+(?:AS\s+)?(\b\w+\b)'
    combined_pattern = f"({pattern})|({pattern_alt})"
    return re.compile(combined_pattern, re.IGNORECASE)

# 查找并替换直接的 table.column 用法
# 修改: 添加捕获组以便于替换，并确保不匹配已加前缀的
def create_direct_usage_pattern_for_replace(table_name, column_name):
    # (?<!...) 是负向先行断言，确保前面不是前缀
    # 分组捕获表名和列名
    pattern = r'(?<!' + PREFIX + r')(?<!\w)(' + re.escape(table_name) + r')\.(' + re.escape(column_name) + r')(?!\w)'
    return re.compile(pattern, re.IGNORECASE)

# 查找并替换 alias.column 用法
# 修改: 添加捕获组以便于替换，确保不匹配已加前缀的列名
def create_alias_usage_pattern_for_replace(alias, column_name):
     # 分组捕获别名和列名
    pattern = r'(?<!\w)(' + re.escape(alias) + r')\.(' + re.escape(column_name) + r')(?!\w)(?!' + PREFIX + r')' # 确保列名后不是前缀 (防止部分匹配如 alias.ced_todo_col) - 可能不需要，因为列名检查更精确
    # 更简单的版本：仅检查列名前没有前缀
    pattern = r'(?<!\w)(' + re.escape(alias) + r')\.(?<!' + PREFIX + r')(' + re.escape(column_name) + r')(?!\w)'
    return re.compile(pattern, re.IGNORECASE)

# 查找并替换 resultMap/result 的 column="column" 用法
# 修改: 添加捕获组以便于替换，确保不匹配已加前缀的
def create_resultmap_column_pattern_for_replace(column_name):
    # 分组捕获 'column="' 部分, 列名, 和结尾引号 '"'
    # (?<!...) 确保列名前面不是前缀
    pattern = r'(\bcolumn\s*=\s*["\'])(?<!' + PREFIX + r')(' + re.escape(column_name) + r')(["\'])'
    return re.compile(pattern, re.IGNORECASE)

# --- 核心处理函数 ---

def parse_target_columns(column_specs):
    """解析 '表名.列名' 列表为字典 (保持不变)"""
    table_column_map = defaultdict(list)
    for spec in column_specs:
        if '.' not in spec:
            logging.warning(f"无效格式: '{spec}'。跳过。预期格式: '表名.列名'")
            continue
        parts = spec.strip().rsplit('.', 1)
        if len(parts) != 2:
             logging.warning(f"无效格式: '{spec}'。跳过。无法分割。")
             continue
        table_name, column_name = parts
        if not table_name or not column_name:
             logging.warning(f"无效格式: '{spec}'。跳过。表名或列名为空。")
             continue
        # 存储时去除前缀，因为检测时要匹配原始名称
        table_column_map[table_name.replace(PREFIX, '')].append(column_name.replace(PREFIX, ''))
    return dict(table_column_map)


def process_and_modify_file(file_path, table_column_map, modified_lines_report):
    """
    读取文件，查找、替换目标字段，并记录修改位置。
    如果发生修改，则写回文件。

    Args:
        file_path (str): XML 文件路径。
        table_column_map (dict): {表名: [列名列表]}。
        modified_lines_report (set): 用于收集 "filepath:linenum" 字符串的集合。

    Returns:
        bool: 如果文件被修改则返回 True，否则 False。
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        logging.error(f"无法读取文件 {file_path}: {e}")
        return False

    new_lines = []
    file_modified = False
    current_aliases = {} # 当前文件内，每个目标表的最新别名

    # --- 预编译所有替换模式 ---
    replace_patterns = defaultdict(list)
    alias_detection_patterns = {table: create_alias_pattern(table) for table in table_column_map}

    for table, columns in table_column_map.items():
        for col in columns:
            # 直接使用: (pattern, replacement_template)
            replace_patterns[(table, col, 'direct')] = (
                create_direct_usage_pattern_for_replace(table, col),
                rf'{PREFIX}\1.{PREFIX}\2' # \1=table, \2=column
            )
            # ResultMap/Result: (pattern, replacement_template)
            replace_patterns[(col, 'resultmap')] = (
                create_resultmap_column_pattern_for_replace(col),
                rf'\1{PREFIX}\2\3' # \1=column=", \2=column, \3="
            )

    # --- 逐行处理 ---
    for line_num, line in enumerate(lines, 1):
        original_line = line
        modified_line = line
        line_was_modified = False

        # 1. 检测别名 (需要在替换前进行，以获得正确的别名)
        for table_name in table_column_map:
            for match in alias_detection_patterns[table_name].finditer(original_line): # 使用原始行检测别名
                alias = match.group(2) or match.group(4)
                if alias and alias.upper() not in ['WHERE', 'SET', 'VALUES', 'ON', 'AND', 'OR', 'AS', 'ORDER', 'GROUP', 'BY', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'JOIN']:
                    current_aliases[table_name] = alias
                    #logging.debug(f"文件 {os.path.basename(file_path)} 行 {line_num}: 找到别名 '{alias}' for '{table_name}'")


        # 2. 应用替换：直接使用 (table.column)
        for (table, col, _type), (pattern, repl) in replace_patterns.items():
            if _type == 'direct':
                 modified_line, count = pattern.subn(repl, modified_line)
                 if count > 0:
                    logging.debug(f"文件 {os.path.basename(file_path)} 行 {line_num}: 替换直接引用 {table}.{col}")
                    line_was_modified = True

        # 3. 应用替换：别名使用 (alias.column)
        # 需要为每个当前有效的别名动态创建模式
        for table_name, alias in current_aliases.items():
            if table_name in table_column_map:
                 for column_name in table_column_map[table_name]:
                    alias_pattern_repl = create_alias_usage_pattern_for_replace(alias, column_name)
                    alias_repl = rf'\1.{PREFIX}\2' # \1=alias, \2=column
                    modified_line, count = alias_pattern_repl.subn(alias_repl, modified_line)
                    if count > 0:
                        logging.debug(f"文件 {os.path.basename(file_path)} 行 {line_num}: 替换别名引用 {alias}.{column_name}")
                        line_was_modified = True

        # 4. 应用替换：ResultMap/Result (column="column")
        # 检查所有需要检查的列
        processed_resultmap_cols = set() # 防止同一行对同一列多次处理（虽然模式本身会防止）
        for table, columns in table_column_map.items():
            for col in columns:
                 if col not in processed_resultmap_cols:
                     pattern_key = (col, 'resultmap')
                     if pattern_key in replace_patterns:
                         pattern, repl = replace_patterns[pattern_key]
                         modified_line, count = pattern.subn(repl, modified_line)
                         if count > 0:
                             logging.debug(f"文件 {os.path.basename(file_path)} 行 {line_num}: 替换ResultMap/Result column=\"{col}\"")
                             line_was_modified = True
                             processed_resultmap_cols.add(col)


        # --- 记录和添加 ---
        if line_was_modified:
            report_key = f"{file_path}:{line_num}"
            modified_lines_report.add(report_key)
            file_modified = True

        new_lines.append(modified_line) # 添加（可能）修改后的行

    # --- 写回文件 (如果发生修改) ---
    if file_modified:
        try:
            # 可选：先创建备份
            # backup_path = file_path + ".bak"
            # shutil.copy2(file_path, backup_path) # copy2 保留元数据
            # logging.info(f"已创建备份: {backup_path}")

            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            logging.info(f"文件已修改: {file_path}")
            return True
        except Exception as e:
            logging.error(f"无法写回文件 {file_path}: {e}")
            # 可选：如果写回失败，尝试恢复备份
            # if os.path.exists(backup_path):
            #     try:
            #         shutil.move(backup_path, file_path)
            #         logging.warning(f"写回失败，已从备份恢复: {file_path}")
            #     except Exception as backup_e:
            #         logging.error(f"!!! 严重错误: 写回失败且无法从备份 {backup_path} 恢复: {backup_e}")
            return False
    else:
        # logging.debug(f"文件无需修改: {file_path}")
        return False

def main():
    # --- 配置区 ---
    SCAN_DIRECTORY = r"D:\proj\b2bmanage\src\main\resources" # 【修改】MyBatis XML 文件根目录
    TARGET_COLUMNS_STR = "tb_sys_receipts_order.shipping_fee,tb_sys_receipts_order.shipping_way,tb_sys_receipts_order.status,oc_customer.country_id" # 【修改】"表名.字段名",逗号分隔
    EXCLUDE_DIRS_STR = "target,build,test" # 【修改】要排除的目录名,逗号分隔
    ENABLE_VERBOSE_LOGGING = False # 是否启用 DEBUG 日志
    # --- 配置区结束 ---

    # --- 安全提示 ---
    print("="*60)
    print("！！！ 重要警告 ！！！")
    print("此脚本将直接修改扫描目录下的 XML 文件。")
    print("强烈建议在运行前备份您的项目或确保代码已提交到版本控制系统 (如 Git)。")
    print("="*60)
    confirm = input("确认要继续执行吗? (输入 'yes' 继续): ")
    if confirm.lower() != 'yes':
        print("操作已取消。")
        return
    # --- 安全提示结束 ---


    if ENABLE_VERBOSE_LOGGING:
        logging.getLogger().setLevel(logging.DEBUG)

    scan_directory = SCAN_DIRECTORY
    target_column_specs = [c.strip() for c in TARGET_COLUMNS_STR.split(',') if c.strip()]
    exclude_dirs = {d.strip() for d in EXCLUDE_DIRS_STR.split(',') if d.strip()}

    if not os.path.isdir(scan_directory):
        logging.error(f"错误: 扫描目录 '{scan_directory}' 不存在或无效。请检查 SCAN_DIRECTORY。")
        return
    if not target_column_specs:
        logging.error("错误: 未指定目标字段。请检查 TARGET_COLUMNS_STR。")
        return

    table_column_map = parse_target_columns(target_column_specs)
    if not table_column_map:
        logging.error("错误: 未找到有效的 '表名.列名' 配置。请检查 TARGET_COLUMNS_STR。")
        return

    logging.info(f"开始扫描并修改目录: {scan_directory}")
    logging.info(f"将为以下表的字段添加 '{PREFIX}' 前缀: {table_column_map}")
    logging.info(f"排除目录: {exclude_dirs if exclude_dirs else '无'}")

    modified_report = set() # 使用集合存储唯一的 "filepath:linenum"
    file_count = 0
    modified_file_count = 0

    for root, dirs, files in os.walk(scan_directory, topdown=True):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for filename in files:
            if filename.lower().endswith(".xml"):
                file_path = os.path.join(root, filename)
                file_count += 1
                logging.debug(f"正在处理文件: {file_path}")
                if process_and_modify_file(file_path, table_column_map, modified_report):
                    modified_file_count += 1

    logging.info(f"处理完成。共检查 {file_count} 个 XML 文件，修改了 {modified_file_count} 个文件。")

    if modified_report:
        print("\n" + "=" * 30 + " 文件修改位置报告 (filepath:linenumber) " + "=" * 30)
        # 排序报告以便查看
        sorted_report = sorted(list(modified_report), key=lambda x: (x.split(':')[0], int(x.split(':')[1])))
        for item in sorted_report:
            print(item)
        print("\n" + "=" * 30 + " 报告结束 " + "=" * 70)
        print(f"\n总共有 {len(modified_report)} 行被修改。请在 IDE 中搜索 '{PREFIX}' 前缀来查找所有修改点并进行检查。")
    else:
        print("\n在扫描的文件中未找到需要修改的目标字段用法。")

if __name__ == "__main__":
    main()
