#!/bin/bash

# 获取第一个参数作为提交信息
mes=$1

# 如果参数为空，提示用户输入
if [ -z "$mes" ]; then
    read -p "请输入提交信息 (Commit Message): " mes
fi

# 如果用户依然没有输入，则退出脚本
if [ -z "$mes" ]; then
    echo "错误：提交信息不能为空！"
    exit 1
fi

# 执行 Git 命令
echo "正在添加文件..."
git add .

echo "正在提交: $mes"
git commit -m "$mes"

# 检查上一步是否成功（防止没有更改时报错直接 push）
if [ $? -eq 0 ]; then
    echo "正在推送到远程仓库..."
    git push
    echo "完成！"
else
    echo "提交失败，请检查是否有文件更改。"
fi