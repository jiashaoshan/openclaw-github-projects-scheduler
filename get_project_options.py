#!/usr/bin/env python3
"""
获取 GitHub Projects 选项 ID 的工具脚本

使用方法:
    1. 先确保已授权: gh auth refresh -s read:project -s project
    2. 运行: python3 get_project_options.py
"""

import json
import subprocess
import sys

def run_gh_command(args):
    """运行 gh CLI 命令"""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"❌ 命令失败: {result.stderr}")
        return None
    return result.stdout

def get_project_fields():
    """获取项目字段和选项"""
    # 获取项目列表
    print("正在获取项目信息...")
    
    # 尝试获取项目字段
    result = run_gh_command([
        "project", "field-list", "3",
        "--owner", "jiashaoshan",
        "--format", "json"
    ])
    
    if not result:
        print("❌ 无法获取项目字段")
        print("请确保已授权: gh auth refresh -s read:project -s project")
        return None
    
    try:
        data = json.loads(result)
        return data
    except json.JSONDecodeError:
        print(f"❌ 无法解析响应: {result}")
        return None

def main():
    print("=" * 60)
    print("GitHub Projects 选项 ID 获取工具")
    print("=" * 60)
    
    # 检查 gh CLI
    result = subprocess.run(["gh", "--version"], capture_output=True)
    if result.returncode != 0:
        print("❌ 请先安装 GitHub CLI: https://cli.github.com/")
        sys.exit(1)
    
    # 检查登录状态
    result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if result.returncode != 0:
        print("❌ 请先登录: gh auth login")
        sys.exit(1)
    
    print("\n正在获取项目字段和选项...")
    fields = get_project_fields()
    
    if not fields:
        print("\n⚠️ 无法自动获取，请手动执行:")
        print("   gh auth refresh -s read:project -s project")
        print("\n授权完成后，再次运行此脚本")
        sys.exit(1)
    
    print("\n✅ 成功获取项目字段信息:\n")
    print(json.dumps(fields, indent=2))
    
    # 提取并显示配置所需的选项 ID
    print("\n" + "=" * 60)
    print("请在 config.json 中添加以下配置:")
    print("=" * 60)
    
    for field in fields.get("fields", []):
        name = field.get("name")
        field_id = field.get("id")
        
        if name == "Status":
            print(f'\n  "status_field_id": "{field_id}",')
            for opt in field.get("options", []):
                opt_name = opt.get("name", "").lower().replace(" ", "_")
                opt_id = opt.get("id")
                print(f'  "status_{opt_name}_id": "{opt_id}",')
        
        elif name == "Agent":
            print(f'\n  "agent_field_id": "{field_id}",')
            agent_options = {}
            for opt in field.get("options", []):
                opt_name = opt.get("name")
                opt_id = opt.get("id")
                agent_options[opt_name] = opt_id
            print(f'  "agent_options": {json.dumps(agent_options, indent=4)},')
        
        elif name == "Start date":
            print(f'\n  "start_date_field_id": "{field_id}",')
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
