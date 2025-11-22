#!/bin/bash

# 杀死现有的进程
ps -ef | grep app.py | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null

# 等待进程完全退出
sleep 3

# 再次检查并强制杀死残留进程
ps -ef | grep app.py | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null

# 等待一下确保进程已终止
sleep 1

# 启动新进程
nohup python3.9 -u app.py >> wechat_robot.log 2>&1 &

echo "应用已启动"
